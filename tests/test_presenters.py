"""Tests for redsun_mimir presenters."""

from __future__ import annotations

import asyncio
import inspect
import json
import threading
from concurrent.futures import Future
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

import bluesky.plan_stubs as bps
import numpy as np
import pytest
import redsun.engine.plan_stubs as rps
from bluesky.run_engine import RunEngineResult
from bluesky.simulators import RunEngineSimulator
from ophyd_async.core import soft_signal_rw
from redsun.aio import run_coro
from redsun.engine import Deferrals, RunEngine

from redsun_mimir.common import LIVE_VIEW_STREAM, MEDIAN_SCAN_STREAM, Roi
from redsun_mimir.device._mocks import MockLightDevice
from redsun_mimir.presenter.acquisition import AcquisitionPresenter
from redsun_mimir.presenter.detector import DetectorPresenter
from redsun_mimir.presenter.light import LightPresenter
from redsun_mimir.presenter.median import SCAN, MedianPresenter
from redsun_mimir.presenter.motor import MotorPresenter
from redsun_mimir.protocols import (
    DescribesDetectors,
    DescribesLights,
    DescribesMotors,
    DetectorProtocol,
)
from tests.conftest import FakeDetector, FakeFlyer, FakeXYStage

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


def root_attributes(store: Path) -> dict[str, Any]:
    """Return the attributes a Zarr v3 array or group at *store* carries."""
    attributes: dict[str, Any] = json.loads((store / "zarr.json").read_text())[
        "attributes"
    ]
    return attributes


async def set_roi(detector: DetectorProtocol, roi: tuple[int, int, int, int]) -> None:
    """Crop *detector* to *roi*, given as ``x, y, width, height``."""
    await detector.roi.set(str(Roi(*roi)))


class EngineHolder:
    """Holds the deferrals of an engine, as the presenter running plans does."""

    def __init__(self, engine: RunEngine) -> None:
        self.deferrals = Deferrals(engine)

    def plan_deferrals(self) -> Deferrals:
        return self.deferrals


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
        self.subs: list[list[Any]] = []

    def __call__(self, plan: Any, subs: list[Any] | None = None) -> FakeFuture:
        self.plans.append(plan)
        self.subs.append(subs or [])
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


class TestMotorPresenter:
    """Tests for MotorPresenter."""

    @pytest.fixture
    def controller(
        self, motor_stage: FakeXYStage
    ) -> Generator[MotorPresenter, None, None]:
        yield MotorPresenter("motor_presenter", motors={motor_stage.name: motor_stage})

    def test_describes_its_motors(self, controller: MotorPresenter) -> None:
        """Describe every axis, and return a readback for each axis read."""
        assert isinstance(controller, DescribesMotors)
        readings = controller.motor_readings()
        assert any("xystage" in k for k in readings)
        assert any("xystage" in k for k in controller.motor_descriptors())
        assert set(controller.devices_readbacks()) == set(readings)

    async def test_move_applies_a_delta(
        self, controller: MotorPresenter, motor_stage: FakeXYStage
    ) -> None:
        """Move an axis by a delta from wherever it stands."""
        await controller.move(motor_stage.name, "x", 10.0)

        assert (await motor_stage.axis["x"].locate())["readback"] == pytest.approx(10.0)

    async def test_move_unknown_motor_raises(self, controller: MotorPresenter) -> None:
        """Raise `KeyError` for a motor the presenter does not track."""
        with pytest.raises(KeyError):
            await controller.move("does-not-exist", "x", 1.0)

    async def test_concurrent_steps_all_apply(
        self, controller: MotorPresenter, motor_stage: FakeXYStage
    ) -> None:
        """Apply both of two moves issued together, one after the other."""
        await asyncio.gather(
            controller.move(motor_stage.name, "x", 10.0),
            controller.move(motor_stage.name, "x", 10.0),
        )

        assert (await motor_stage.axis["x"].locate())["readback"] == pytest.approx(20.0)

    async def test_opposite_steps_cancel_out(
        self, controller: MotorPresenter, motor_stage: FakeXYStage
    ) -> None:
        """Net two opposite moves issued together to zero."""
        await asyncio.gather(
            controller.move(motor_stage.name, "x", 10.0),
            controller.move(motor_stage.name, "x", -10.0),
        )

        assert (await motor_stage.axis["x"].locate())["readback"] == pytest.approx(0.0)


class TestLightPresenter:
    """Tests for LightPresenter."""

    @pytest.fixture
    def devices(
        self, mock_led: MockLightDevice, mock_laser: MockLightDevice
    ) -> dict[str, MockLightDevice]:
        return {"led": mock_led, "laser": mock_laser}

    @pytest.fixture
    def controller(self, devices: dict[str, MockLightDevice]) -> LightPresenter:
        return LightPresenter("light_presenter", lights=devices)

    def test_describes_its_lights(self, controller: LightPresenter) -> None:
        """Describe and read every light source."""
        assert isinstance(controller, DescribesLights)
        assert any("led" in k for k in controller.light_readings())
        assert any("led" in k for k in controller.light_descriptors())

    async def test_trigger_toggles_led(
        self, controller: LightPresenter, mock_led: MockLightDevice
    ) -> None:
        """Toggle a light source on and off."""
        assert await mock_led.enabled.get_value() is False
        await controller.trigger("led")
        assert await mock_led.enabled.get_value() is True
        await controller.trigger("led")
        assert await mock_led.enabled.get_value() is False

    async def test_set_intensity(
        self, controller: LightPresenter, mock_laser: MockLightDevice
    ) -> None:
        """Set the intensity of a light source."""
        await controller.set("laser", 75.0)
        assert await mock_laser.intensity.get_value() == pytest.approx(75.0)

    async def test_binary_source_refuses_intensity(
        self, mock_binary_led: MockLightDevice
    ) -> None:
        """Ignore an intensity asked of a binary source."""
        ctrl = LightPresenter("light_presenter", lights={"binary_led": mock_binary_led})

        await ctrl.set("binary_led", 42.0)

        assert await mock_binary_led.intensity.get_value() == pytest.approx(0.0)

    async def test_binary_source_still_toggles(
        self, mock_binary_led: MockLightDevice
    ) -> None:
        """Toggle a binary source."""
        ctrl = LightPresenter("light_presenter", lights={"binary_led": mock_binary_led})

        await ctrl.trigger("binary_led")

        assert await mock_binary_led.enabled.get_value() is True


class TestMedianPresenter:
    """Tests for the document-driven MedianPresenter."""

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
        """Emit the median once and write the stack, with its positions, to the capture's store."""
        frames = [np.full((4, 4), i, dtype="uint16") for i in range(3)]
        store = tmp_path / "acquisition.zarr"
        buf = soft_signal_rw(np.ndarray, initial_value=frames[0], name="cam-buffer")
        devices: dict[str, Any] = {"cam": _MedianSource(buffer=buf)}
        presenter = MedianPresenter("median_presenter", sources=devices)
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
        """Write no stack for a capture with no scan behind it."""
        frames = [np.full((4, 4), i, dtype="uint16") for i in range(3)]
        store = tmp_path / "acquisition.zarr"
        buf = soft_signal_rw(np.ndarray, initial_value=frames[0], name="cam-buffer")
        devices: dict[str, Any] = {"cam": _MedianSource(buffer=buf)}
        presenter = MedianPresenter("median_presenter", sources=devices)
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
        """Close at shutdown a store a capture left open, so its stack is readable."""
        frames = [np.full((4, 4), i, dtype="uint16") for i in range(3)]
        store = tmp_path / "acquisition.zarr"
        buf = soft_signal_rw(np.ndarray, initial_value=frames[0], name="cam-buffer")
        devices: dict[str, Any] = {"cam": _MedianSource(buffer=buf)}
        presenter = MedianPresenter("median_presenter", sources=devices)
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
        """Divide live frames by the cached median and publish them as their own layer."""
        buf = soft_signal_rw(
            np.ndarray,
            initial_value=np.zeros((4, 4), dtype="uint16"),
            name="cam-buffer",
        )
        devices: dict[str, Any] = {"cam": _MedianSource(buffer=buf)}
        presenter = MedianPresenter("median_presenter", sources=devices)

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
        """Correct monitored live frames on a real engine after a scan."""
        buf = soft_signal_rw(
            np.ndarray,
            initial_value=np.zeros((4, 4), dtype="uint16"),
            name="cam-buffer",
        )
        devices: dict[str, Any] = {"cam": _MedianSource(buffer=buf)}
        presenter = MedianPresenter("median_presenter", sources=devices)

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
        """Emit no corrected frame before any scan."""
        buf = soft_signal_rw(
            np.ndarray,
            initial_value=np.zeros((4, 4), dtype="uint16"),
            name="cam-buffer",
        )
        devices: dict[str, Any] = {"cam": _MedianSource(buffer=buf)}
        presenter = MedianPresenter("median_presenter", sources=devices)

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
        """Ignore a stream carrying no tracked buffer."""
        buf = soft_signal_rw(
            np.ndarray,
            initial_value=np.zeros((4, 4), dtype="uint16"),
            name="cam-buffer",
        )
        other = soft_signal_rw(float, initial_value=0.0, name="other-signal")
        devices: dict[str, Any] = {"cam": _MedianSource(buffer=buf)}
        presenter = MedianPresenter("median_presenter", sources=devices)

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

    def test_the_square_scan_takes_a_frame_before_every_move(
        self, fake_detector: FakeDetector, motor_stage: FakeXYStage
    ) -> None:
        """Take a frame before every move, so the stack starts where the motor stands."""
        presenter = MedianPresenter("median_ctrl", sources={})
        simulator = RunEngineSimulator()
        simulator.add_handler("locate", lambda msg: {"readback": 0.0, "setpoint": 0.0})

        messages = simulator.simulate_plan(
            presenter.square_scan([fake_detector], motor_stage, 5.0, 1)
        )

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


class TestDetectorPresenter:
    """Tests for DetectorPresenter."""

    @pytest.fixture
    def controller(
        self, fake_detector: FakeDetector
    ) -> Generator[DetectorPresenter, None, None]:
        yield DetectorPresenter(
            "det_ctrl", detectors={fake_detector.name: fake_detector}
        )

    def test_instantiation(
        self, controller: DetectorPresenter, fake_detector: FakeDetector
    ) -> None:
        """Track the detector and the data key of its buffer."""
        assert fake_detector.name in controller.detectors
        assert fake_detector.buffer.name in controller._buffer_keys

    def test_describes_its_detectors(self, controller: DetectorPresenter) -> None:
        """Describe, read and lay out every detector."""
        assert isinstance(controller, DescribesDetectors)
        assert "cam" in controller.detector_layer_specs()
        assert "cam-exposure" in controller.detector_readings()

    def test_a_setting_the_presenter_cannot_write_is_described_read_only(
        self, controller: DetectorPresenter
    ) -> None:
        """Append `:readonly` to the source of a setting the presenter cannot write."""
        described = controller.detector_descriptors()

        assert described["cam-sensor_size"]["source"].endswith(":readonly")
        assert not described["cam-pixel_dtype"]["source"].endswith(":readonly")
        assert not described["cam-exposure"]["source"].endswith(":readonly")
        assert not described["cam-roi"]["source"].endswith(":readonly")

    def test_live_events_are_forwarded_raw(
        self, controller: DetectorPresenter, fake_detector: FakeDetector
    ) -> None:
        """Forward the frames of a live event unmodified."""
        key = fake_detector.buffer.name
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
        assert received[0][f"{fake_detector.name}-roi"]["value"] == Roi.parse(
            run_coro(fake_detector.roi.get_value())
        )

    def test_a_frame_is_forwarded_with_the_roi_it_was_taken_with(
        self, fake_detector: FakeDetector
    ) -> None:
        """Forward a frame with the ROI it was taken with."""
        presenter = DetectorPresenter("det_ctrl", detectors={"cam": fake_detector})
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
        """Stop following the ROIs at shutdown."""
        presenter = DetectorPresenter("det_ctrl", detectors={"cam": fake_detector})
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
        """Size a layer as the whole sensor, whatever the ROI."""
        run_coro(set_roi(fake_detector, (1, 1, 3, 2)))

        specs = DetectorPresenter(
            "det_ctrl", detectors={"cam": fake_detector}
        ).detector_layer_specs()

        assert specs["cam"]["shape"] == (4, 6)

    def test_events_from_unknown_streams_are_ignored(
        self, controller: DetectorPresenter
    ) -> None:
        """Ignore an event whose descriptor was never routed."""
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
        self, fake_detector: FakeDetector
    ) -> None:
        """Apply a ROI asked for during a plan between two of its messages."""
        engine = RunEngine()
        presenter = DetectorPresenter("det_ctrl", detectors={"cam": fake_detector})
        presenter.setup(EngineHolder(engine))
        announced: list[tuple[str, str, Any]] = []
        presenter.sig_new_configuration.connect(lambda *args: announced.append(args))
        # a message the test holds open, so the change cannot land before the
        # assertions on whatever machine runs them
        gate = asyncio.Event()
        entered = threading.Event()

        async def hold() -> None:
            entered.set()
            await gate.wait()

        def held_open() -> MsgGenerator[None]:
            yield from bps.wait_for([hold])

        future = engine(held_open())
        assert await asyncio.to_thread(entered.wait, 5)

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
        fake_detector: FakeDetector,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Log a setting the device refuses, and announce nothing."""
        received: list[tuple[str, str, Any]] = []
        controller.sig_new_configuration.connect(
            lambda d, k, v: received.append((d, k, v))
        )

        await controller.set(fake_detector.name, "exposure", "not a number")

        assert received == []
        assert "Failed to set" in caplog.text

    async def test_set_exposure_emits_new_configuration(
        self, controller: DetectorPresenter, fake_detector: FakeDetector
    ) -> None:
        """Apply a setting and announce its new value."""
        received: list[tuple[str, str, Any]] = []
        controller.sig_new_configuration.connect(
            lambda d, k, v: received.append((d, k, v))
        )
        await controller.set(fake_detector.name, "exposure", 50.0)

        assert received
        assert received[0][0] == fake_detector.name
        assert run_coro(fake_detector.exposure.get_value()) == pytest.approx(50.0)


class TestAcquisitionPresenter:
    """Tests for AcquisitionPresenter."""

    @pytest.fixture
    def devices(
        self, fake_flyer: FakeFlyer, motor_stage: FakeXYStage
    ) -> dict[str, Any]:
        return {fake_flyer.name: fake_flyer, motor_stage.name: motor_stage}

    @pytest.fixture
    def controller(
        self, devices: dict[str, Any]
    ) -> Generator[AcquisitionPresenter, None, None]:
        ctrl = AcquisitionPresenter("acq_ctrl", devices=devices)
        ctrl.setup({ctrl.name: ctrl}, {})
        yield ctrl
        ctrl.shutdown()

    def test_setup_collects_the_plans_of_every_component(
        self, devices: dict[str, Any]
    ) -> None:
        """Collect the plans of every component offering them, its own included."""
        acquisition = AcquisitionPresenter("acq_ctrl", devices=devices)
        median = MedianPresenter("median_ctrl", sources={})
        try:
            acquisition.setup({"acq_ctrl": acquisition, "median_ctrl": median}, {})
        finally:
            acquisition.shutdown()

        assert set(acquisition.plan_specs) == {"live_stream", "live_median_scan"}

    def test_a_plan_no_device_can_fill_is_left_out(self) -> None:
        """Leave out a plan asking for a device the session does not have."""
        acquisition = AcquisitionPresenter("acq_ctrl", devices={})
        try:
            acquisition.setup({"acq_ctrl": acquisition}, {})
        finally:
            acquisition.shutdown()

        assert acquisition.plan_specs == {}

    def test_a_run_gets_the_callbacks_of_its_plan_then_the_attached_ones(
        self,
        devices: dict[str, Any],
        fake_flyer: FakeFlyer,
        motor_stage: FakeXYStage,
    ) -> None:
        """Subscribe for each run only its plan's callbacks and the attached ones."""
        acquisition = AcquisitionPresenter("acq_ctrl", devices=devices)
        median = MedianPresenter("median_ctrl", sources={fake_flyer.name: fake_flyer})
        detector = DetectorPresenter(
            "det_ctrl", detectors={fake_flyer.name: fake_flyer}
        )
        acquisition.setup(
            {"acq_ctrl": acquisition, "median_ctrl": median},
            {"det_ctrl": detector, "median_ctrl": median},
        )
        first, second = FakeFuture(), FakeFuture()
        engine = FakeEngine(first)
        acquisition.engine = engine  # type: ignore[assignment]

        acquisition.launch_plan(
            "live_median_scan",
            {"detectors": [fake_flyer.name], "motor": motor_stage.name},
            ["det_ctrl"],
        )
        first.settle()
        engine.future = second
        acquisition.launch_plan("live_stream", {"detectors": [fake_flyer.name]})
        second.settle()

        assert engine.subs == [[median, detector], []]

    def test_an_action_reaches_the_component_offering_the_running_plan(
        self,
        devices: dict[str, Any],
        fake_flyer: FakeFlyer,
        motor_stage: FakeXYStage,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Pass an action request to the actions of the running plan's component."""
        acquisition = AcquisitionPresenter("acq_ctrl", devices=devices)
        median = MedianPresenter("median_ctrl", sources={fake_flyer.name: fake_flyer})
        acquisition.setup({"acq_ctrl": acquisition, "median_ctrl": median}, {})
        acquisition.engine = FakeEngine(FakeFuture())  # type: ignore[assignment]
        acquisition.launch_plan(
            "live_median_scan",
            {"detectors": [fake_flyer.name], "motor": motor_stage.name},
        )
        waiting = median.actions.wait(SCAN)
        next(waiting)

        acquisition.request_action("scan", True)

        wait_message = next(waiting)
        assert wait_message.args[0]["scan"].is_set()
        assert "refused" not in caplog.text

    def test_launch_plan_argument_round_trip_and_pre_launch_notify(
        self,
        controller: AcquisitionPresenter,
        fake_flyer: FakeFlyer,
        motor_stage: FakeXYStage,
    ) -> None:
        """Resolve the values the view sends into a plan, and announce its name first."""
        engine = FakeEngine(FakeFuture())
        controller.engine = engine  # type: ignore[assignment]

        notified: list[str] = []
        controller.sig_pre_launch_notify.connect(notified.append)

        controller.launch_plan(
            "live_stream",
            {"detectors": [fake_flyer.name], "frames": 3},
        )

        assert notified == ["live_stream"]
        assert len(engine.plans) == 1
        assert inspect.isgenerator(engine.plans[0])

    def test_a_continuous_plan_announces_its_end(
        self, controller: AcquisitionPresenter, fake_flyer: FakeFlyer
    ) -> None:
        """Announce the end of a continuous plan."""
        settled = FakeFuture()
        controller.engine = FakeEngine(settled)  # type: ignore[assignment]
        ended: list[bool] = []
        controller.sig_plan_done.connect(lambda: ended.append(True))

        controller.launch_plan("live_stream", {"detectors": [fake_flyer.name]})
        settled.settle()

        assert ended == [True]

    def test_a_wrapped_plan_locks_its_devices_until_it_ends(
        self,
        controller: AcquisitionPresenter,
        fake_detector: FakeDetector,
        motor_stage: FakeXYStage,
    ) -> None:
        """Announce the devices a wrapped plan locks, then none once it ends."""
        seen: list[frozenset[str]] = []
        controller.sig_locks_changed.connect(seen.append)

        controller.engine(
            rps.lock_wrapper(bps.null(), motor_stage, fake_detector)
        ).result(timeout=10)

        assert seen == [{motor_stage.name, fake_detector.name}, frozenset()]

    def test_a_failing_wrapped_plan_unlocks(
        self, controller: AcquisitionPresenter, motor_stage: FakeXYStage
    ) -> None:
        """Unlock the devices of a wrapped plan that fails."""
        seen: list[frozenset[str]] = []
        controller.sig_locks_changed.connect(seen.append)

        def fail() -> MsgGenerator[None]:
            yield from bps.null()
            raise RuntimeError("the plan failed")

        with pytest.raises(RuntimeError):
            controller.engine(rps.lock_wrapper(fail(), motor_stage)).result(timeout=10)

        assert seen == [{motor_stage.name}, frozenset()]

    def test_stopping_an_idle_engine_is_nothing(
        self, controller: AcquisitionPresenter
    ) -> None:
        """Do nothing when asked to stop an idle engine."""
        controller.engine = FakeEngine(FakeFuture(), state="idle")  # type: ignore[assignment]

        controller.stop_plan()

    def test_a_launch_while_a_plan_runs_is_refused(
        self, controller: AcquisitionPresenter, fake_flyer: FakeFlyer
    ) -> None:
        """Refuse to launch a plan while another runs."""
        engine = FakeEngine(FakeFuture())
        controller.engine = engine  # type: ignore[assignment]
        running: Future[None] = Future()
        controller.futures.add(running)
        try:
            controller.launch_plan("live_stream", {"detectors": [fake_flyer.name]})
        finally:
            controller.futures.discard(running)

        assert engine.plans == []
