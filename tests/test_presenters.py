"""Tests for redsun_mimir presenters."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

import bluesky.plan_stubs as bps
import numpy as np
import pytest
from ophyd_async.core import soft_signal_rw
from redsun.aio import run_coro
from redsun.engine import RunEngine
from redsun.storage import BaseStorage, SessionPathProvider
from redsun.storage.backends._memory import MemoryIO
from redsun.virtual import VirtualContainer

from redsun_mimir.device._mocks import MockLightDevice
from redsun_mimir.presenter.acquisition import AcquisitionPresenter
from redsun_mimir.presenter.detector import DetectorPresenter
from redsun_mimir.presenter.light import LightPresenter
from redsun_mimir.presenter.median import MedianPresenter
from redsun_mimir.presenter.motor import MotorPresenter
from redsun_mimir.providers import (
    DETECTOR_LAYER_SPECS,
    LIGHT_CONFIGURATION,
    MOTOR_DESCRIPTION,
    MOTOR_READINGS,
)
from redsun_mimir.streams import LIVE_VIEW_STREAM, MEDIAN_SCAN_STREAM
from tests.conftest import FakeXYStage

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from bluesky.utils import MsgGenerator
    from event_model.documents import Event, EventDescriptor, RunStop
    from ophyd_async.core import SignalRW

    from redsun_mimir.device.mmcore import MMDemoCamera


class TestMotorPresenter:
    """Tests for MotorPresenter."""

    @pytest.fixture
    def controller(
        self, motor_stage: FakeXYStage
    ) -> Generator[MotorPresenter, None, None]:
        ctrl = MotorPresenter("motor_presenter", {motor_stage.name: motor_stage})
        yield ctrl
        ctrl.shutdown()

    def test_instantiation(
        self, controller: MotorPresenter, motor_stage: FakeXYStage
    ) -> None:
        """Controller identifies the motor device and its axes."""
        assert motor_stage.name in controller._motors
        assert set(controller._motors[motor_stage.name].axis.keys()) == {"x", "y"}

    def test_register_providers(
        self, controller: MotorPresenter, virtual_container: VirtualContainer
    ) -> None:
        """register_providers() binds the motor snapshots to their keys."""
        controller.register_providers(virtual_container)
        readings = virtual_container.require(MOTOR_READINGS)
        description = virtual_container.require(MOTOR_DESCRIPTION)
        assert any("xystage" in k for k in readings)
        assert any("xystage" in k for k in description)

    async def test_move_applies_a_delta_and_emits(
        self, controller: MotorPresenter, motor_stage: FakeXYStage
    ) -> None:
        """move() displaces the axis and announces where it asked it to go."""
        received: list[tuple[str, str, float]] = []
        controller.sig_new_position.connect(lambda m, a, p: received.append((m, a, p)))

        await controller.move(motor_stage.name, "x", 10.0)

        assert len(received) == 1
        motor, axis, position = received[0]
        assert (motor, axis) == (motor_stage.name, "x")
        assert position == pytest.approx(10.0)
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

    def test_instantiation(self, controller: LightPresenter) -> None:
        """Controller identifies and stores light devices."""
        assert "led" in controller._lights
        assert "laser" in controller._lights

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


@dataclass
class _MedianSource:
    """Minimal stand-in for a device MedianPresenter can track.

    Only ``buffer`` (a named signal) and ``storage`` are inspected.
    """

    buffer: SignalRW[np.ndarray]
    storage: BaseStorage


class TestMedianPresenter:
    """Tests for the document-driven MedianPresenter."""

    def test_instantiation_tracks_only_buffered_storage_devices(
        self, motor_stage: FakeXYStage
    ) -> None:
        """Only devices exposing both `buffer` and `storage` are tracked."""
        buf = soft_signal_rw(
            np.ndarray, initial_value=np.zeros((2, 2)), name="cam-buffer"
        )
        storage = BaseStorage(
            io=MemoryIO(), path_provider=SessionPathProvider(session="s")
        )
        devices: dict[str, Any] = {
            "cam": _MedianSource(buffer=buf, storage=storage),
            "motor": motor_stage,
        }
        presenter = MedianPresenter("median_presenter", devices)
        assert "cam-buffer" in presenter._storages
        assert len(presenter._storages) == 1

    async def test_document_flow_computes_writes_and_emits_median(
        self, tmp_path: Path
    ) -> None:
        """descriptor->events->stop produces the median, emits it once, writes one frame."""
        io = MemoryIO()
        storage = BaseStorage(
            io=io,
            path_provider=SessionPathProvider(base_dir=tmp_path, session="median"),
        )
        frames = [np.full((4, 4), i, dtype="uint16") for i in range(3)]
        buf = soft_signal_rw(np.ndarray, initial_value=frames[0], name="cam-buffer")
        devices: dict[str, Any] = {"cam": _MedianSource(buffer=buf, storage=storage)}
        presenter = MedianPresenter("median_presenter", devices)

        received: list[dict[str, Any]] = []
        presenter.frames.median.connect(received.append)

        engine = RunEngine()
        engine.subscribe(presenter)

        def plan() -> MsgGenerator[None]:
            yield from bps.open_run()
            yield from bps.declare_stream(buf, name=MEDIAN_SCAN_STREAM)
            for frame in frames:
                yield from bps.abs_set(buf, frame, wait=True)
                yield from bps.trigger_and_read([buf], name=MEDIAN_SCAN_STREAM)
            yield from bps.close_run()

        engine(plan()).result(timeout=30)
        run_coro(storage.close())

        expected = np.median(np.stack(frames), axis=0).astype("uint16")
        np.testing.assert_array_equal(presenter.medians["cam-buffer"], expected)

        assert len(received) == 1
        emitted_reading = next(iter(received[0].values()))
        np.testing.assert_array_equal(emitted_reading["value"], expected)

        assert len(io.stores) == 1
        written = io.stores[0].arrays["cam_median"]
        assert len(written) == 1
        np.testing.assert_array_equal(written[0], expected)

    async def test_live_frames_are_divided_by_the_cached_median(
        self, tmp_path: Path
    ) -> None:
        """After a scan, live frames are corrected and published as their own layer.

        This is the whole point of the presenter: cache the background stack,
        reduce it to a median, then divide every subsequent live frame by it.
        """
        storage = BaseStorage(
            io=MemoryIO(),
            path_provider=SessionPathProvider(base_dir=tmp_path, session="median"),
        )
        buf = soft_signal_rw(
            np.ndarray,
            initial_value=np.zeros((4, 4), dtype="uint16"),
            name="cam-buffer",
        )
        devices: dict[str, Any] = {"cam": _MedianSource(buffer=buf, storage=storage)}
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
        for _ in range(3):
            presenter.event(
                cast(
                    "Event",
                    {
                        "descriptor": "scan-desc",
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
        storage = BaseStorage(
            io=MemoryIO(),
            path_provider=SessionPathProvider(base_dir=tmp_path, session="live"),
        )
        buf = soft_signal_rw(
            np.ndarray,
            initial_value=np.zeros((4, 4), dtype="uint16"),
            name="cam-buffer",
        )
        devices: dict[str, Any] = {"cam": _MedianSource(buffer=buf, storage=storage)}
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
        storage = BaseStorage(
            io=MemoryIO(), path_provider=SessionPathProvider(session="s")
        )
        buf = soft_signal_rw(
            np.ndarray,
            initial_value=np.zeros((4, 4), dtype="uint16"),
            name="cam-buffer",
        )
        devices: dict[str, Any] = {"cam": _MedianSource(buffer=buf, storage=storage)}
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
        io = MemoryIO()
        storage = BaseStorage(
            io=io,
            path_provider=SessionPathProvider(base_dir=tmp_path, session="median"),
        )
        buf = soft_signal_rw(
            np.ndarray,
            initial_value=np.zeros((4, 4), dtype="uint16"),
            name="cam-buffer",
        )
        other = soft_signal_rw(float, initial_value=0.0, name="other-signal")
        devices: dict[str, Any] = {"cam": _MedianSource(buffer=buf, storage=storage)}
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
        assert len(io.stores) == 0


class TestDetectorPresenter:
    """Tests for DetectorPresenter."""

    @pytest.fixture
    def controller(
        self, mm_camera: MMDemoCamera
    ) -> Generator[DetectorPresenter, None, None]:
        yield DetectorPresenter("det_ctrl", {mm_camera.name: mm_camera})

    def test_instantiation(
        self, controller: DetectorPresenter, mm_camera: MMDemoCamera
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

    def test_live_events_are_forwarded_raw(
        self, controller: DetectorPresenter, mm_camera: MMDemoCamera
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

    async def test_set_exposure_emits_new_configuration(
        self, controller: DetectorPresenter, mm_camera: MMDemoCamera
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
    def devices(
        self, mm_camera: MMDemoCamera, motor_stage: FakeXYStage
    ) -> dict[str, Any]:
        return {mm_camera.name: mm_camera, motor_stage.name: motor_stage}

    @pytest.fixture
    def controller(
        self, devices: dict[str, Any]
    ) -> Generator[AcquisitionPresenter, None, None]:
        ctrl = AcquisitionPresenter("acq_ctrl", devices)
        yield ctrl
        ctrl.shutdown()

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

    def test_launch_plan_argument_round_trip_and_pre_launch_notify(
        self,
        controller: AcquisitionPresenter,
        mm_camera: MMDemoCamera,
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

    def test_toggle_action_event_unknown_action_raises(
        self, controller: AcquisitionPresenter
    ) -> None:
        """toggle_action_event() on a name with no registered latch raises KeyError."""
        with pytest.raises(KeyError):
            controller.toggle_action_event("does-not-exist", True)
