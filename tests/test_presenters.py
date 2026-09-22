"""Tests for redsun_mimir presenters."""

from __future__ import annotations

import asyncio
import inspect
import json
from concurrent.futures import Future
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

import bluesky.plan_stubs as bps
import numpy as np
import pytest
from bluesky.run_engine import RunEngineResult
from bluesky.simulators import RunEngineSimulator
from ophyd_async.core import soft_signal_rw
from redsun.aio import run_coro
from redsun.engine import DEFERRALS, Deferrals, RunEngine
from redsun.engine.actions import SRLatch
from redsun.virtual import VirtualContainer
from redsun.writers._base import root_attributes

from redsun_mimir.common import LIVE_VIEW_STREAM, MEDIAN_SCAN_STREAM, Roi
from redsun_mimir.device._mocks import MockLightDevice
from redsun_mimir.presenter.acquisition import AcquisitionPresenter
from redsun_mimir.presenter.detector import DetectorPresenter
from redsun_mimir.presenter.light import LightPresenter
from redsun_mimir.presenter.median import MedianPresenter
from redsun_mimir.presenter.motor import MotorPresenter
from redsun_mimir.protocols import DetectorProtocol
from redsun_mimir.providers import (
    DETECTOR_DESCRIPTORS,
    DETECTOR_LAYER_SPECS,
    LIGHT_CONFIGURATION,
    MOTOR_DESCRIPTION,
    MOTOR_READBACKS,
    MOTOR_READINGS,
)
from tests.conftest import FakeDetector, FakeXYStage

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path

    from bluesky.utils import MsgGenerator
    from event_model.documents import (
        Event,
        EventDescriptor,
        RunStop,
    )
    from ophyd_async.core import SignalRW

    from redsun_mimir.device.mmcore import MMCamera


class TestMotorPresenter:
    """Tests for MotorPresenter."""

    @pytest.fixture
    def controller(
        self, motor_stage: FakeXYStage
    ) -> Generator[MotorPresenter, None, None]:
        ctrl = MotorPresenter("motor_presenter", {motor_stage.name: motor_stage})
        yield ctrl
        ctrl.shutdown()

    def test_register_providers(
        self, controller: MotorPresenter, virtual_container: VirtualContainer
    ) -> None:
        """register_providers() binds the motor snapshots to their keys."""
        controller.register_providers(virtual_container)
        readings = virtual_container.require(MOTOR_READINGS)
        description = virtual_container.require(MOTOR_DESCRIPTION)
        readbacks = virtual_container.require(MOTOR_READBACKS)
        assert any("xystage" in k for k in readings)
        assert any("xystage" in k for k in description)
        assert set(readbacks) == set(readings)

    async def test_move_applies_a_delta(
        self, controller: MotorPresenter, motor_stage: FakeXYStage
    ) -> None:
        """move() displaces the axis from wherever it currently is."""
        await controller.move(motor_stage.name, "x", 10.0)

        assert (await motor_stage.axis["x"].locate())["readback"] == pytest.approx(10.0)

    async def test_move_unknown_motor_raises(self, controller: MotorPresenter) -> None:
        """move() on a name that is not a tracked motor raises KeyError."""
        with pytest.raises(KeyError):
            await controller.move("does-not-exist", "x", 1.0)

    async def test_concurrent_steps_all_apply(
        self, controller: MotorPresenter, motor_stage: FakeXYStage
    ) -> None:
        """Two moves issued together are two displacements, not one.

        The emitter no longer blocks, so both requests are in flight at once.
        Without the per-device lock each would read the same starting position
        and the second would overwrite rather than add.
        """
        await asyncio.gather(
            controller.move(motor_stage.name, "x", 10.0),
            controller.move(motor_stage.name, "x", 10.0),
        )

        assert (await motor_stage.axis["x"].locate())["readback"] == pytest.approx(20.0)

    async def test_opposite_steps_cancel_out(
        self, controller: MotorPresenter, motor_stage: FakeXYStage
    ) -> None:
        """A reversal issued mid-move nets to zero rather than racing."""
        await asyncio.gather(
            controller.move(motor_stage.name, "x", 10.0),
            controller.move(motor_stage.name, "x", -10.0),
        )

        assert (await motor_stage.axis["x"].locate())["readback"] == pytest.approx(0.0)

    def test_shutdown_does_not_raise(self, motor_stage: FakeXYStage) -> None:
        """shutdown() completes even for a device with no async shutdown."""
        ctrl = MotorPresenter("motor_presenter", {motor_stage.name: motor_stage})
        ctrl.shutdown()  # must not raise


class TestLightPresenter:
    """Tests for LightPresenter."""

    @pytest.fixture
    def devices(
        self, mock_led: MockLightDevice, mock_laser: MockLightDevice
    ) -> dict[str, MockLightDevice]:
        return {"led": mock_led, "laser": mock_laser}

    @pytest.fixture
    def controller(self, devices: dict[str, MockLightDevice]) -> LightPresenter:
        return LightPresenter("light_presenter", devices)

    def test_register_providers(
        self, controller: LightPresenter, virtual_container: VirtualContainer
    ) -> None:
        """register_providers() binds the light snapshots to their keys."""
        controller.register_providers(virtual_container)
        cfg = virtual_container.require(LIGHT_CONFIGURATION)
        assert any("led" in k for k in cfg)

    async def test_trigger_toggles_led(
        self, controller: LightPresenter, mock_led: MockLightDevice
    ) -> None:
        """trigger() toggles the target light source (async method)."""
        assert await mock_led.enabled.get_value() is False
        await controller.trigger("led")
        assert await mock_led.enabled.get_value() is True
        await controller.trigger("led")
        assert await mock_led.enabled.get_value() is False

    async def test_set_intensity(
        self, controller: LightPresenter, mock_laser: MockLightDevice
    ) -> None:
        """set() updates the intensity of the target light source (async method)."""
        await controller.set("laser", 75.0)
        assert await mock_laser.intensity.get_value() == pytest.approx(75.0)

    async def test_binary_source_refuses_intensity(
        self, mock_binary_led: MockLightDevice
    ) -> None:
        """A binary source keeps the signal but ignores requests to set it."""
        ctrl = LightPresenter("light_presenter", {"binary_led": mock_binary_led})

        await ctrl.set("binary_led", 42.0)

        assert await mock_binary_led.intensity.get_value() == pytest.approx(0.0)

    async def test_binary_source_still_toggles(
        self, mock_binary_led: MockLightDevice
    ) -> None:
        """Only intensity is refused; on/off is the whole point of the device."""
        ctrl = LightPresenter("light_presenter", {"binary_led": mock_binary_led})

        await ctrl.trigger("binary_led")

        assert await mock_binary_led.enabled.get_value() is True

    def test_non_light_devices_are_excluded(self, motor_stage: FakeXYStage) -> None:
        """A device that does not satisfy LightProtocol is not included in _lights."""
        devices: dict[str, Any] = {"motor": motor_stage}
        ctrl = LightPresenter("light_presenter", devices)
        assert "motor" not in ctrl._lights


async def set_roi(detector: DetectorProtocol, roi: tuple[int, int, int, int]) -> None:
    """Crop *detector* to *roi*, given as ``x, y, width, height``."""
    await detector.roi.set(str(Roi(*roi)))


class FakeFuture:
    """A future the test settles by hand, running the callbacks it was given."""

    def __init__(self) -> None:
        self.callbacks: list[Callable[[FakeFuture], None]] = []

    def add_done_callback(self, callback: Callable[[FakeFuture], None]) -> None:
        self.callbacks.append(callback)

    def settle(self) -> None:
        for callback in self.callbacks:
            callback(self)


class FakeEngine:
    """Records the plans it is handed, and hands back one future."""

    def __init__(self, future: FakeFuture, state: str = "running") -> None:
        self.future = future
        self.state = state
        self.plans: list[Any] = []

    def __call__(self, plan: Any) -> FakeFuture:
        self.plans.append(plan)
        return self.future

    def stop(self) -> None:
        raise RuntimeError("RunEngine is already idle.")

    def abort(self) -> None:
        """No-op: satisfies AcquisitionPresenter.shutdown()'s abort path."""


@dataclass
class _MedianSource:
    """Minimal stand-in for a device MedianPresenter can track.

    Only ``buffer``, a named signal, is inspected.
    """

    buffer: SignalRW[np.ndarray]


class TestMedianPresenter:
    """Tests for the document-driven MedianPresenter."""

    def test_instantiation_tracks_only_buffered_devices(
        self, motor_stage: FakeXYStage
    ) -> None:
        """Only devices exposing a `buffer` are tracked."""
        buf = soft_signal_rw(
            np.ndarray, initial_value=np.zeros((2, 2)), name="cam-buffer"
        )
        devices: dict[str, Any] = {
            "cam": _MedianSource(buffer=buf),
            "motor": motor_stage,
        }
        presenter = MedianPresenter("median_presenter", devices)
        assert presenter._sources == {"cam-buffer"}

    @staticmethod
    def capture(presenter: MedianPresenter, store: Path, scan_run: str | None) -> None:
        """Run a capture: a run of its own naming ``cam`` and its *store*, then its stop."""
        presenter(
            "start",
            {
                "uid": "capture",
                "time": 0.0,
                "purpose": "capture",
                "parent": "outer",
                "median_scan": scan_run,
            },
        )
        presenter(
            "descriptor",
            {
                "uid": "capture-desc",
                "run_start": "capture",
                "name": "live_stream",
                "data_keys": {
                    "cam": {
                        "source": store.as_uri(),
                        "dtype": "array",
                        "dtype_numpy": "<u2",
                        "shape": [1, 4, 4],
                        "external": "STREAM:",
                    }
                },
            },
        )
        presenter(
            "stream_resource",
            {
                "uid": "capture-res",
                "run_start": "capture",
                "data_key": "cam",
                "mimetype": "application/x-zarr",
                "uri": store.as_uri(),
                "parameters": {},
            },
        )
        presenter(
            "stop",
            {
                "uid": "capture-stop",
                "run_start": "capture",
                "time": 1.0,
                "exit_status": "success",
            },
        )

    @staticmethod
    def scan_uid(result: RunEngineResult | tuple[str, ...]) -> str:
        """Return the uid of the one run *result* carries."""
        uids = result.run_start_uids if isinstance(result, RunEngineResult) else result
        (uid,) = uids
        return uid

    @staticmethod
    def scan(
        buf: SignalRW[np.ndarray],
        frames: list[np.ndarray],
        motor: FakeXYStage | None = None,
    ) -> MsgGenerator[None]:
        """Run a square scan: the frames on the median stream, then its stop.

        With *motor*, its ``x`` axis steps by 5 before each frame and both axes
        are read into the frame's event.
        """
        readables: list[Any] = [buf] if motor is None else [buf, motor]
        yield from bps.open_run()
        yield from bps.declare_stream(*readables, name=MEDIAN_SCAN_STREAM)
        for frame in frames:
            if motor is not None:
                yield from bps.mvr(motor.axis["x"], 5.0)
            yield from bps.abs_set(buf, frame, wait=True)
            yield from bps.trigger_and_read(readables, name=MEDIAN_SCAN_STREAM)
        yield from bps.close_run()

    async def test_document_flow_computes_writes_and_emits_median(
        self, tmp_path: Path, motor_stage: FakeXYStage
    ) -> None:
        """descriptor->events->stop produces the median, emits it once, writes it.

        The scan and the capture are runs nested in the live plan's; the store
        is the one the capture names, and the scan's stack lands in it as a key
        of its own once the capture stops, naming the scan it came from and
        carrying one record per frame, its id and the axis positions it was
        taken at.
        """
        frames = [np.full((4, 4), i, dtype="uint16") for i in range(3)]
        store = tmp_path / "acquisition.zarr"
        buf = soft_signal_rw(np.ndarray, initial_value=frames[0], name="cam-buffer")
        devices: dict[str, Any] = {"cam": _MedianSource(buffer=buf)}
        presenter = MedianPresenter("median_presenter", devices)
        received: list[dict[str, Any]] = []
        presenter.frames.median.connect(received.append)
        engine = RunEngine()
        engine.subscribe(presenter)

        presenter("start", {"uid": "outer", "time": 0.0})
        scan_run = self.scan_uid(
            engine(self.scan(buf, frames, motor_stage)).result(timeout=30)
        )
        self.capture(presenter, store, scan_run)

        expected = np.median(np.stack(frames), axis=0).astype("uint16")
        np.testing.assert_array_equal(presenter.medians["cam-buffer"], expected)
        assert len(received) == 1
        emitted_reading = next(iter(received[0].values()))
        np.testing.assert_array_equal(emitted_reading["value"], expected)
        written = json.loads((store / "cam_scan" / "zarr.json").read_text())
        assert written["shape"] == [3, 4, 4]
        assert root_attributes(store / "cam_scan")["derived_from"] == "cam"
        assert root_attributes(store / "cam_scan")["stream"] == MEDIAN_SCAN_STREAM
        assert root_attributes(store / "cam_scan")["scan_run"] == scan_run
        assert root_attributes(store / "cam_scan")["positions"] == [
            {
                "frame_id": 1,
                "axes": {"xystage-axis-x": 5.0, "xystage-axis-y": 0.0},
            },
            {
                "frame_id": 2,
                "axes": {"xystage-axis-x": 10.0, "xystage-axis-y": 0.0},
            },
            {
                "frame_id": 3,
                "axes": {"xystage-axis-x": 15.0, "xystage-axis-y": 0.0},
            },
        ]
        assert root_attributes(store / "cam_scan")["redsun"]["run_start"] == "capture"

    async def test_a_capture_before_the_scan_gets_no_stack(
        self, tmp_path: Path
    ) -> None:
        """A capture with no scan behind it names no scan and takes nothing."""
        frames = [np.full((4, 4), i, dtype="uint16") for i in range(3)]
        store = tmp_path / "acquisition.zarr"
        buf = soft_signal_rw(np.ndarray, initial_value=frames[0], name="cam-buffer")
        devices: dict[str, Any] = {"cam": _MedianSource(buffer=buf)}
        presenter = MedianPresenter("median_presenter", devices)
        engine = RunEngine()
        engine.subscribe(presenter)

        presenter("start", {"uid": "outer", "time": 0.0})
        self.capture(presenter, store, None)
        assert not store.exists()
        scan_run = self.scan_uid(engine(self.scan(buf, frames)).result(timeout=30))
        self.capture(presenter, tmp_path / "second.zarr", scan_run)

        assert not store.exists()
        written = json.loads(
            (tmp_path / "second.zarr" / "cam_scan" / "zarr.json").read_text()
        )
        assert written["shape"] == [3, 4, 4]

    async def test_shutdown_closes_a_store_the_run_left_open(
        self, tmp_path: Path
    ) -> None:
        frames = [np.full((4, 4), i, dtype="uint16") for i in range(3)]
        store = tmp_path / "acquisition.zarr"
        buf = soft_signal_rw(np.ndarray, initial_value=frames[0], name="cam-buffer")
        devices: dict[str, Any] = {"cam": _MedianSource(buffer=buf)}
        presenter = MedianPresenter("median_presenter", devices)
        engine = RunEngine()
        engine.subscribe(presenter)
        presenter("start", {"uid": "outer", "time": 0.0})
        scan_run = self.scan_uid(engine(self.scan(buf, frames)).result(timeout=30))
        presenter("start", {"uid": "capture", "time": 0.0, "median_scan": scan_run})
        presenter(
            "descriptor",
            {
                "uid": "capture-desc",
                "run_start": "capture",
                "name": "live_stream",
                "data_keys": {
                    "cam": {
                        "source": store.as_uri(),
                        "dtype": "array",
                        "dtype_numpy": "<u2",
                        "shape": [1, 4, 4],
                        "external": "STREAM:",
                    }
                },
            },
        )
        presenter(
            "stream_resource",
            {
                "uid": "capture-res",
                "run_start": "capture",
                "data_key": "cam",
                "mimetype": "application/x-zarr",
                "uri": store.as_uri(),
                "parameters": {},
            },
        )

        presenter.shutdown()

        assert json.loads((store / "cam_scan" / "zarr.json").read_text())["shape"] == [
            3,
            4,
            4,
        ]

    async def test_live_frames_are_divided_by_the_cached_median(
        self, tmp_path: Path
    ) -> None:
        """After a scan, live frames are corrected and published as their own layer.

        This is the whole point of the presenter: cache the background stack,
        reduce it to a median, then divide every subsequent live frame by it.
        """
        buf = soft_signal_rw(
            np.ndarray,
            initial_value=np.zeros((4, 4), dtype="uint16"),
            name="cam-buffer",
        )
        devices: dict[str, Any] = {"cam": _MedianSource(buffer=buf)}
        presenter = MedianPresenter("median_presenter", devices)

        filtered: list[dict[str, Any]] = []
        presenter.frames.filtered.connect(filtered.append)

        # scan phase: a constant background of 2
        presenter.descriptor(
            cast(
                "EventDescriptor",
                {
                    "uid": "scan-desc",
                    "run_start": "scan-run",
                    "name": MEDIAN_SCAN_STREAM,
                    "data_keys": {"cam-buffer": {"shape": [4, 4]}},
                },
            )
        )
        background = np.full((4, 4), 2, dtype="uint16")
        for seq_num in range(1, 4):
            presenter.event(
                cast(
                    "Event",
                    {
                        "descriptor": "scan-desc",
                        "seq_num": seq_num,
                        "time": 0.0,
                        "data": {"cam-buffer": background},
                    },
                )
            )
        presenter.stop(
            cast("RunStop", {"run_start": "scan-run", "time": 1.0, "uid": "stop-1"})
        )

        assert filtered == [], "no live frame has arrived yet"

        # live phase: frames on any other stream get corrected
        presenter.descriptor(
            cast(
                "EventDescriptor",
                {
                    "uid": "live-desc",
                    "run_start": "live-run",
                    "name": LIVE_VIEW_STREAM,
                    "data_keys": {"cam-buffer": {"shape": [4, 4]}},
                },
            )
        )
        presenter.event(
            cast(
                "Event",
                {
                    "descriptor": "live-desc",
                    "time": 2.0,
                    "data": {"cam-buffer": np.full((4, 4), 8, dtype="uint16")},
                },
            )
        )

        assert len(filtered) == 1
        # keyed for its own viewer layer, distinct from the raw one
        assert set(filtered[0]) == {"cam_filtered"}
        np.testing.assert_allclose(
            filtered[0]["cam_filtered"]["value"], np.full((4, 4), 4.0)
        )

    async def test_monitor_drives_the_correction_through_the_run_engine(
        self, tmp_path: Path
    ) -> None:
        """End-to-end: bps.monitor turns live frames into corrected documents.

        Pins the whole pipeline the presenter exists for - scan documents in,
        median out, then every monitored live frame divided by it - against a
        real RunEngine rather than hand-built documents.
        """
        buf = soft_signal_rw(
            np.ndarray,
            initial_value=np.zeros((4, 4), dtype="uint16"),
            name="cam-buffer",
        )
        devices: dict[str, Any] = {"cam": _MedianSource(buffer=buf)}
        presenter = MedianPresenter("median_presenter", devices)

        filtered: list[dict[str, Any]] = []
        presenter.frames.filtered.connect(filtered.append)

        engine = RunEngine()
        engine.subscribe(presenter)

        background = np.full((4, 4), 2, dtype="uint16")

        def scan() -> MsgGenerator[None]:
            yield from bps.open_run()
            yield from bps.declare_stream(buf, name=MEDIAN_SCAN_STREAM)
            for _ in range(3):
                yield from bps.abs_set(buf, background, wait=True)
                yield from bps.trigger_and_read([buf], name=MEDIAN_SCAN_STREAM)
            yield from bps.close_run()

        def live() -> MsgGenerator[None]:
            yield from bps.open_run()
            yield from bps.monitor(buf, name=LIVE_VIEW_STREAM)
            yield from bps.abs_set(buf, np.full((4, 4), 8, dtype="uint16"), wait=True)
            yield from bps.sleep(0.05)
            yield from bps.unmonitor(buf)
            yield from bps.close_run()

        engine(scan()).result(timeout=30)
        np.testing.assert_array_equal(presenter.medians["cam-buffer"], background)

        engine(live()).result(timeout=30)

        assert filtered, "bps.monitor produced no corrected frames"
        values = [entry["cam_filtered"]["value"] for entry in filtered]
        # the last monitored frame is the 8 written above, divided by 2
        np.testing.assert_allclose(values[-1], np.full((4, 4), 4.0))

    async def test_live_frames_without_a_median_are_not_emitted(self) -> None:
        """Before any scan there is no background to divide by."""
        buf = soft_signal_rw(
            np.ndarray,
            initial_value=np.zeros((4, 4), dtype="uint16"),
            name="cam-buffer",
        )
        devices: dict[str, Any] = {"cam": _MedianSource(buffer=buf)}
        presenter = MedianPresenter("median_presenter", devices)

        filtered: list[dict[str, Any]] = []
        presenter.frames.filtered.connect(filtered.append)

        presenter.descriptor(
            cast(
                "EventDescriptor",
                {
                    "uid": "live-desc",
                    "run_start": "live-run",
                    "name": LIVE_VIEW_STREAM,
                    "data_keys": {"cam-buffer": {"shape": [4, 4]}},
                },
            )
        )
        presenter.event(
            cast(
                "Event",
                {
                    "descriptor": "live-desc",
                    "time": 0.0,
                    "data": {"cam-buffer": np.full((4, 4), 8, dtype="uint16")},
                },
            )
        )

        assert filtered == []

    async def test_descriptor_ignores_unrelated_sources(self, tmp_path: Path) -> None:
        """A descriptor whose data_keys do not include a tracked buffer is ignored."""
        buf = soft_signal_rw(
            np.ndarray,
            initial_value=np.zeros((4, 4), dtype="uint16"),
            name="cam-buffer",
        )
        other = soft_signal_rw(float, initial_value=0.0, name="other-signal")
        devices: dict[str, Any] = {"cam": _MedianSource(buffer=buf)}
        presenter = MedianPresenter("median_presenter", devices)

        received: list[dict[str, Any]] = []
        presenter.frames.median.connect(received.append)

        engine = RunEngine()
        engine.subscribe(presenter)

        def plan() -> MsgGenerator[None]:
            yield from bps.open_run()
            yield from bps.declare_stream(other, name="unrelated")
            yield from bps.trigger_and_read([other], name="unrelated")
            yield from bps.close_run()

        engine(plan()).result(timeout=30)

        assert received == []
        assert presenter.medians == {}


class TestDetectorPresenter:
    """Tests for DetectorPresenter."""

    @pytest.fixture
    def controller(
        self, mm_camera: MMCamera
    ) -> Generator[DetectorPresenter, None, None]:
        yield DetectorPresenter("det_ctrl", {mm_camera.name: mm_camera})

    def test_instantiation(
        self, controller: DetectorPresenter, mm_camera: MMCamera
    ) -> None:
        """Controller identifies the detector device and its buffer key."""
        assert mm_camera.name in controller.detectors
        assert mm_camera.buffer.name in controller._buffer_keys

    def test_register_providers(
        self, controller: DetectorPresenter, virtual_container: VirtualContainer
    ) -> None:
        """register_providers() populates detector providers on the container."""
        controller.register_providers(virtual_container)
        specs = virtual_container.require(DETECTOR_LAYER_SPECS)
        assert "camera1" in specs

    def test_a_setting_the_presenter_cannot_write_is_described_read_only(
        self, controller: DetectorPresenter, virtual_container: VirtualContainer
    ) -> None:
        """The settings tree greys a source ending in ``:readonly``."""
        controller.register_providers(virtual_container)
        described = virtual_container.require(DETECTOR_DESCRIPTORS)

        assert described["camera1-sensor_size"]["source"].endswith(":readonly")
        assert not described["camera1-pixel_dtype"]["source"].endswith(":readonly")
        assert not described["camera1-exposure"]["source"].endswith(":readonly")
        assert not described["camera1-roi"]["source"].endswith(":readonly")

    def test_live_events_are_forwarded_raw(
        self, controller: DetectorPresenter, mm_camera: MMCamera
    ) -> None:
        """Frames arrive as Event documents and are forwarded unmodified.

        Median correction belongs to MedianPresenter, which publishes it on
        its own signal as a separate layer.
        """
        key = mm_camera.buffer.name
        received: list[dict[str, Any]] = []
        controller.sig_new_data.connect(received.append)

        controller.descriptor(
            cast(
                "EventDescriptor",
                {"uid": "desc-1", "run_start": "run-1", "data_keys": {key: {}}},
            )
        )
        frame = np.full((4, 4), 8.0, dtype=np.float32)
        controller.event(
            cast(
                "Event",
                {"descriptor": "desc-1", "time": 0.0, "data": {key: frame}},
            )
        )

        assert len(received) == 1
        np.testing.assert_array_equal(received[0][key]["value"], frame)
        assert received[0][f"{mm_camera.name}-roi"]["value"] == Roi.parse(
            run_coro(mm_camera.roi.get_value())
        )

    def test_a_frame_is_forwarded_with_the_roi_it_was_taken_with(
        self, fake_detector: FakeDetector
    ) -> None:
        """A cropped frame is placed by its ROI, so the two travel together."""
        presenter = DetectorPresenter("det_ctrl", {"cam": fake_detector})
        received: list[dict[str, Any]] = []
        presenter.sig_new_data.connect(received.append)
        presenter.descriptor(
            cast(
                "EventDescriptor",
                {
                    "uid": "desc-1",
                    "run_start": "run-1",
                    "data_keys": {"cam-buffer": {}},
                },
            )
        )
        event = cast(
            "Event",
            {
                "descriptor": "desc-1",
                "time": 0.0,
                "data": {"cam-buffer": np.zeros((2, 3))},
            },
        )

        run_coro(set_roi(fake_detector, (1, 1, 3, 2)))
        presenter.event(event)

        assert received[-1]["cam-roi"]["value"] == Roi(1, 1, 3, 2)
        assert list(received[-1]) == ["cam-roi", "cam-buffer"]

    def test_shutdown_stops_following_the_rois(
        self, fake_detector: FakeDetector
    ) -> None:
        """No subscription outlives the presenter, so none is left pending."""
        presenter = DetectorPresenter("det_ctrl", {"cam": fake_detector})
        received: list[dict[str, Any]] = []
        presenter.sig_new_data.connect(received.append)
        presenter.descriptor(
            cast(
                "EventDescriptor",
                {
                    "uid": "desc-1",
                    "run_start": "run-1",
                    "data_keys": {"cam-buffer": {}},
                },
            )
        )
        event = cast(
            "Event",
            {
                "descriptor": "desc-1",
                "time": 0.0,
                "data": {"cam-buffer": np.zeros((2, 3))},
            },
        )

        presenter.shutdown()
        run_coro(set_roi(fake_detector, (1, 1, 3, 2)))
        presenter.event(event)

        assert received[-1]["cam-roi"]["value"] == Roi(0, 0, 6, 4)

    def test_a_layer_is_the_size_of_the_sensor_whatever_the_roi(
        self, fake_detector: FakeDetector
    ) -> None:
        run_coro(set_roi(fake_detector, (1, 1, 3, 2)))

        specs = DetectorPresenter("det_ctrl", {"cam": fake_detector}).layer_specs()

        assert specs["cam"]["shape"] == (4, 6)

    def test_events_from_unknown_streams_are_ignored(
        self, controller: DetectorPresenter
    ) -> None:
        """An event whose descriptor was never routed emits nothing."""
        received: list[dict[str, Any]] = []
        controller.sig_new_data.connect(received.append)

        controller.event(
            cast(
                "Event",
                {"descriptor": "never-seen", "time": 0.0, "data": {"x": 1.0}},
            )
        )

        assert received == []

    async def test_a_roi_change_during_a_plan_lands_between_two_messages(
        self, fake_detector: FakeDetector, virtual_container: VirtualContainer
    ) -> None:
        """Applied inside a point, a ROI would put two frame shapes in one stream."""
        engine = RunEngine()
        virtual_container.provide(DEFERRALS, Deferrals(engine))
        presenter = DetectorPresenter("det_ctrl", {"cam": fake_detector})
        presenter.inject_dependencies(virtual_container)
        announced: list[tuple[str, str, Any]] = []
        presenter.sig_new_configuration.connect(lambda *args: announced.append(args))
        # a message the test holds open, so the change cannot land before the
        # assertions on whatever machine runs them
        gate = asyncio.Event()

        def held_open() -> MsgGenerator[None]:
            yield from bps.wait_for([gate.wait])

        future = engine(held_open())
        while engine.state != "running":
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.05)

        await presenter.set("cam", "roi", "1,1,3,2")
        await presenter.set("cam", "exposure", 5.0)

        assert await fake_detector.roi.get_value() == "0,0,6,4"
        assert await fake_detector.exposure.get_value() == 5.0
        engine.loop.call_soon_threadsafe(gate.set)
        future.result(timeout=5)
        assert await fake_detector.roi.get_value() == "1,1,3,2"
        assert ("cam", "cam-roi", "1,1,3,2") in announced

    async def test_a_refused_setting_is_logged_and_not_announced(
        self,
        controller: DetectorPresenter,
        mm_camera: MMCamera,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A write the device refuses reaches the log, not the caller's slot."""
        received: list[tuple[str, str, Any]] = []
        controller.sig_new_configuration.connect(
            lambda d, k, v: received.append((d, k, v))
        )

        await controller.set(mm_camera.name, "exposure", "not a number")

        assert received == []
        assert "Failed to set" in caplog.text

    async def test_set_exposure_emits_new_configuration(
        self, controller: DetectorPresenter, mm_camera: MMCamera
    ) -> None:
        """set() applies the setting and emits sig_new_configuration."""
        received: list[tuple[str, str, Any]] = []
        controller.sig_new_configuration.connect(
            lambda d, k, v: received.append((d, k, v))
        )
        await controller.set(mm_camera.name, "exposure", 50.0)

        assert received
        assert received[0][0] == mm_camera.name
        assert run_coro(mm_camera.exposure.get_value()) == pytest.approx(50.0)


class TestAcquisitionPresenter:
    """Tests for AcquisitionPresenter."""

    @pytest.fixture
    def devices(self, mm_camera: MMCamera, motor_stage: FakeXYStage) -> dict[str, Any]:
        return {mm_camera.name: mm_camera, motor_stage.name: motor_stage}

    @pytest.fixture
    def controller(
        self, devices: dict[str, Any]
    ) -> Generator[AcquisitionPresenter, None, None]:
        ctrl = AcquisitionPresenter("acq_ctrl", devices)
        yield ctrl
        ctrl.shutdown()

    def test_a_directory_request_is_announced_when_no_plan_runs(
        self, controller: AcquisitionPresenter
    ) -> None:
        """The session's path provider learns where a run writes from here."""
        announced: list[str] = []
        controller.sig_base_dir_changed.connect(announced.append)

        controller.set_base_dir("D:/mimir-data")

        assert announced == ["D:/mimir-data"]

    def test_a_directory_request_during_a_plan_is_refused(
        self, controller: AcquisitionPresenter
    ) -> None:
        """A run's files belong under one root, so the change waits for it.

        The path provider refuses such a change itself, raising into whatever
        emitted it; this keeps the request from reaching it at all.
        """
        announced: list[str] = []
        controller.sig_base_dir_changed.connect(announced.append)
        running: Future[None] = Future()
        controller.futures.add(running)
        try:
            controller.set_base_dir("D:/mimir-data")
        finally:
            # the presenter reads this set to know a plan is in flight, and
            # its own shutdown reads it too
            controller.futures.discard(running)

        assert announced == []

    def test_registered_callbacks_are_subscribed_by_default(
        self,
        devices: dict[str, Any],
        virtual_container: VirtualContainer,
    ) -> None:
        """Every registered document callback reaches the engine.

        Live visualization and median filtering are document-driven, so a
        callback that is registered but never subscribed is a silently blank
        viewer - which is exactly what an empty default produced.
        """
        detector = DetectorPresenter("det_ctrl", devices)
        median = MedianPresenter("median_ctrl", devices)
        acquisition = AcquisitionPresenter("acq_ctrl", devices)
        try:
            for presenter in (detector, median, acquisition):
                presenter.register_providers(virtual_container)
            # only the acquisition presenter still has one: the others lost
            # theirs with the connections they used to make
            acquisition.inject_dependencies(virtual_container)

            assert set(virtual_container.callbacks) == {"det_ctrl", "median_ctrl"}
            assert set(acquisition.callback_tokens) == set(virtual_container.callbacks)
        finally:
            acquisition.shutdown()

    def test_explicit_callback_list_restricts_the_selection(
        self,
        devices: dict[str, Any],
        virtual_container: VirtualContainer,
    ) -> None:
        """An explicit list still wins; an empty list subscribes nothing."""
        detector = DetectorPresenter("det_ctrl", devices)
        median = MedianPresenter("median_ctrl", devices)
        acquisition = AcquisitionPresenter("acq_ctrl", devices, callbacks=["det_ctrl"])
        try:
            for presenter in (detector, median, acquisition):
                presenter.register_providers(virtual_container)
            # only the acquisition presenter still has one: the others lost
            # theirs with the connections they used to make
            acquisition.inject_dependencies(virtual_container)

            assert set(acquisition.callback_tokens) == {"det_ctrl"}
        finally:
            acquisition.shutdown()

    def test_plan_specs_built_for_both_plans_with_matching_devices(
        self, controller: AcquisitionPresenter
    ) -> None:
        """Both live_stream and live_median_scan get a PlanSpec when devices match."""
        assert set(controller.plan_specs) == {"live_stream", "live_median_scan"}

    def test_plan_specs_empty_without_matching_devices(self) -> None:
        """A required Sequence[ReadableFlyer]/MotorProtocol param with no match skips the plan."""
        ctrl = AcquisitionPresenter("acq_ctrl", {})
        assert ctrl.plan_specs == {}

    def test_the_square_scan_takes_a_frame_before_every_move(
        self, fake_detector: FakeDetector, motor_stage: FakeXYStage
    ) -> None:
        """The stack starts where the motor stands; the last move closes the square."""
        presenter = AcquisitionPresenter("acq_ctrl", {})
        simulator = RunEngineSimulator()
        simulator.add_handler("locate", lambda msg: {"readback": 0.0, "setpoint": 0.0})

        try:
            messages = simulator.simulate_plan(
                presenter.square_scan([fake_detector], motor_stage, 5.0, 1)
            )
        finally:
            presenter.shutdown()

        assert [
            (msg.command, getattr(msg.obj, "name", None))
            for msg in messages
            if msg.command in {"trigger", "save", "set"}
        ] == [
            ("trigger", "cam"),
            ("save", None),
            ("set", "xystage-axis-x"),
            ("trigger", "cam"),
            ("save", None),
            ("set", "xystage-axis-y"),
            ("trigger", "cam"),
            ("save", None),
            ("set", "xystage-axis-x"),
            ("trigger", "cam"),
            ("save", None),
            ("set", "xystage-axis-y"),
        ]

    def test_launch_plan_argument_round_trip_and_pre_launch_notify(
        self,
        controller: AcquisitionPresenter,
        mm_camera: MMCamera,
        motor_stage: FakeXYStage,
    ) -> None:
        """launch_plan() resolves UI values into real devices and fires sig_pre_launch_notify.

        The real ``RunEngine`` is swapped for a recording stub: plan
        functions are lazy generators, so building the call is enough to
        exercise ``resolve_arguments``/``collect_arguments`` without
        actually driving bluesky messages through a background thread.
        """

        class _FakeFuture:
            def add_done_callback(self, callback: Any) -> None:
                del callback

        calls: list[Any] = []

        class _FakeEngine:
            def __call__(self, plan: Any) -> _FakeFuture:
                calls.append(plan)
                return _FakeFuture()

            def abort(self) -> None:
                """No-op: satisfies AcquisitionPresenter.shutdown()'s abort path."""

        controller.engine = _FakeEngine()  # type: ignore[assignment]

        notified: list[str] = []
        controller.sig_pre_launch_notify.connect(notified.append)

        controller.launch_plan(
            "live_stream",
            {"detectors": [mm_camera.name], "frames": 3},
        )

        assert notified == ["live_stream"]
        assert len(calls) == 1
        assert inspect.isgenerator(calls[0])

    def test_a_togglable_plan_announces_its_end(
        self, controller: AcquisitionPresenter, mm_camera: MMCamera
    ) -> None:
        """The path provider and the view learn a stream ended, not only a scan."""
        settled = FakeFuture()
        controller.engine = FakeEngine(settled)  # type: ignore[assignment]
        ended: list[bool] = []
        controller.sig_plan_done.connect(lambda: ended.append(True))

        controller.launch_plan("live_stream", {"detectors": [mm_camera.name]})
        settled.settle()

        assert ended == [True]

    def test_stopping_an_idle_engine_is_nothing(
        self, controller: AcquisitionPresenter
    ) -> None:
        """A Stop after a plan ended on its own must not raise into a Qt slot."""
        controller.engine = FakeEngine(FakeFuture(), state="idle")  # type: ignore[assignment]

        controller.stop_plan()

    def test_a_launch_while_a_plan_runs_is_refused(
        self, controller: AcquisitionPresenter, mm_camera: MMCamera
    ) -> None:
        """A second plan would take the running one's action latches with it."""
        engine = FakeEngine(FakeFuture())
        controller.engine = engine  # type: ignore[assignment]
        running: Future[None] = Future()
        controller.futures.add(running)
        try:
            controller.launch_plan("live_stream", {"detectors": [mm_camera.name]})
        finally:
            controller.futures.discard(running)

        assert engine.plans == []

    def test_a_latch_left_set_by_a_stop_does_not_fire_the_next_launch(
        self, controller: AcquisitionPresenter, mm_camera: MMCamera
    ) -> None:
        controller.engine = FakeEngine(FakeFuture())  # type: ignore[assignment]
        stale = SRLatch()
        stale.set()
        controller.action_map["stream"] = stale

        controller.launch_plan("live_stream", {"detectors": [mm_camera.name]})

        assert not stale.is_set()

    def test_toggle_action_event_unknown_action_raises(
        self, controller: AcquisitionPresenter
    ) -> None:
        """toggle_action_event() on a name with no registered latch raises KeyError."""
        with pytest.raises(KeyError):
            controller.toggle_action_event("does-not-exist", True)
