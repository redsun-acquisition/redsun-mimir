from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING, Any

import numpy as np
import numpy.typing as npt
import pytest
from redsun.engine import get_shared_loop
from redsun.virtual import VirtualContainer

from redsun_mimir.device._mocks import MockLightDevice
from redsun_mimir.device.mmcore import MMCoreStageDevice
from redsun_mimir.presenter.light import LightPresenter
from redsun_mimir.presenter.median import MedianPresenter
from redsun_mimir.presenter.motor import MotorPresenter
from tests.conftest import MockBufferDevice, make_descriptor, make_start, make_stop

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator


class TestMotorPresenter:
    """Tests for MotorPresenter."""

    @pytest.fixture
    async def controller(
        self,
        xy_mock_motor: MMCoreStageDevice,
        virtual_container: VirtualContainer,
    ) -> AsyncGenerator[MotorPresenter, None]:
        devices = {xy_mock_motor.name: xy_mock_motor}
        ctrl = MotorPresenter("motor_presenter", devices)
        yield ctrl
        ctrl.shutdown()

    def test_instantiation(self, controller: MotorPresenter) -> None:
        """Controller initialises and identifies motor axes."""
        assert "xystage" in controller._axes
        assert set(controller._axes["xystage"]) == {"x", "y"}

    def test_register_providers(
        self, controller: MotorPresenter, virtual_container: VirtualContainer
    ) -> None:
        """register_providers() populates motor_configuration on the container."""
        controller.register_providers(virtual_container)
        assert hasattr(virtual_container, "motor_configuration")
        cfg = virtual_container.motor_configuration()
        assert any("xystage" in k for k in cfg)

    def test_move_updates_position(
        self,
        controller: MotorPresenter,
        xy_mock_motor: MMCoreStageDevice,
    ) -> None:
        """move() dispatches an async move and emits sigNewPosition on completion."""
        done = threading.Event()
        received: list[tuple[str, str, float]] = []

        def on_position(m: str, a: str, p: float) -> None:
            received.append((m, a, p))
            done.set()

        controller.sigNewPosition.connect(on_position)
        controller.move("xystage", "x", 10.0)
        completed = done.wait(2.0)
        assert completed, "sigNewPosition was not emitted in time"

        motor_name, axis, pos = received[0]
        assert motor_name == "xystage"
        assert axis == "x"
        assert pos == pytest.approx(10.0)
        assert asyncio.run_coroutine_threadsafe(
            xy_mock_motor.x.position.get_value(),
            get_shared_loop(),
        ).result() == pytest.approx(10.0)

    def test_move_via_device_name(
        self,
        controller: MotorPresenter,
        xy_mock_motor: MMCoreStageDevice,
    ) -> None:
        """move() accepts the bare device name."""
        done = threading.Event()
        controller.sigNewPosition.connect(lambda m, a, p: done.set())
        controller.move(xy_mock_motor.name, "x", 5.0)
        completed = done.wait(2.0)
        assert completed, "sigNewPosition was not emitted in time"
        assert asyncio.run_coroutine_threadsafe(
            xy_mock_motor.x.position.get_value(),
            get_shared_loop(),
        ).result() == pytest.approx(5.0)

    def test_configure_step_size(
        self,
        controller: MotorPresenter,
        xy_mock_motor: MMCoreStageDevice,
    ) -> None:
        """configure() updates the step size and emits sigNewConfiguration."""
        received: list[tuple[str, dict[str, bool]]] = []
        controller.sigNewConfiguration.connect(lambda m, r: received.append((m, r)))
        step_key = "xystage-x-step_size"
        result = controller.configure("xystage", {step_key: 0.5})
        assert result.get(step_key) is True
        assert asyncio.run_coroutine_threadsafe(
            xy_mock_motor.x.step_size.get_value(),
            get_shared_loop(),
        ).result() == pytest.approx(0.5)
        assert len(received) == 1

    def test_configure_via_device_name(
        self,
        controller: MotorPresenter,
        xy_mock_motor: MMCoreStageDevice,
    ) -> None:
        """configure() accepts the bare device name."""
        step_key = f"{xy_mock_motor.name}-x-step_size"
        result = controller.configure(xy_mock_motor.name, {step_key: 2.0})
        assert result.get(step_key) is True
        assert asyncio.run_coroutine_threadsafe(
            xy_mock_motor.x.step_size.get_value(),
            get_shared_loop(),
        ).result() == pytest.approx(2.0)


class TestLightPresenter:
    """Tests for LightPresenter."""

    @pytest.fixture
    def devices(
        self, mock_led: MockLightDevice, mock_laser: MockLightDevice
    ) -> dict[str, MockLightDevice]:
        return {"led": mock_led, "laser": mock_laser}

    @pytest.fixture
    def controller(
        self,
        devices: dict[str, MockLightDevice],
        virtual_container: VirtualContainer,
    ) -> Generator[LightPresenter, None, None]:
        yield LightPresenter("light_presenter", devices)

    def test_instantiation(self, controller: LightPresenter) -> None:
        """Controller identifies and stores light devices."""
        assert "led" in controller._lights
        assert "laser" in controller._lights

    def test_register_providers(
        self, controller: LightPresenter, virtual_container: VirtualContainer
    ) -> None:
        """register_providers() populates light_configuration on the container."""
        controller.register_providers(virtual_container)
        assert hasattr(virtual_container, "light_configuration")
        cfg = virtual_container.light_configuration()
        assert any("led" in k for k in cfg)

    def test_trigger_toggles_led(
        self,
        controller: LightPresenter,
        mock_led: MockLightDevice,
    ) -> None:
        """trigger() toggles the target light source."""
        loop = get_shared_loop()
        assert (
            asyncio.run_coroutine_threadsafe(
                mock_led.enabled.get_value(), loop
            ).result()
            is False
        )
        controller.trigger("led")
        assert (
            asyncio.run_coroutine_threadsafe(
                mock_led.enabled.get_value(), loop
            ).result()
            is True
        )
        controller.trigger("led")
        assert (
            asyncio.run_coroutine_threadsafe(
                mock_led.enabled.get_value(), loop
            ).result()
            is False
        )

    def test_trigger_via_device_name(
        self,
        controller: LightPresenter,
        mock_led: MockLightDevice,
    ) -> None:
        """trigger() accepts the bare device name."""
        loop = get_shared_loop()
        assert (
            asyncio.run_coroutine_threadsafe(
                mock_led.enabled.get_value(), loop
            ).result()
            is False
        )
        controller.trigger(mock_led.name)
        assert (
            asyncio.run_coroutine_threadsafe(
                mock_led.enabled.get_value(), loop
            ).result()
            is True
        )

    def test_set_intensity(
        self,
        controller: LightPresenter,
        mock_laser: MockLightDevice,
    ) -> None:
        """set() updates the intensity of the target light source."""
        controller.set("laser", 75.0)
        assert asyncio.run_coroutine_threadsafe(
            mock_laser.intensity.get_value(), get_shared_loop()
        ).result() == pytest.approx(75.0)

    def test_set_intensity_via_device_name(
        self,
        controller: LightPresenter,
        mock_laser: MockLightDevice,
    ) -> None:
        """set() accepts the bare device name."""
        controller.set(mock_laser.name, 42.0)
        assert asyncio.run_coroutine_threadsafe(
            mock_laser.intensity.get_value(), get_shared_loop()
        ).result() == pytest.approx(42.0)

    def test_non_light_devices_are_excluded(
        self,
        xy_mock_motor: MMCoreStageDevice,
        virtual_container: VirtualContainer,
    ) -> None:
        """MotorDevice is not included in _lights even if passed in devices."""
        devices: dict[str, Any] = {"motor": xy_mock_motor}
        ctrl = LightPresenter("light_presenter", devices)
        assert "motor" not in ctrl._lights


class TestMedianPresenter:
    """Tests for MedianPresenter (buffer-subscription model)."""

    @pytest.fixture
    def presenter(self, mock_buffer_device: MockBufferDevice) -> MedianPresenter:
        return MedianPresenter(
            "median_presenter",
            {"camera1": mock_buffer_device},
            median_streams=["square_scan"],
            live_streams=["live"],
        )

    async def test_instantiation_no_hints(self) -> None:
        """Presenter accepts median_streams and live_streams parameters."""
        p = MedianPresenter(
            "p",
            {},
            median_streams=["square_scan"],
            live_streams=["live"],
        )
        assert p.median_streams == frozenset({"square_scan"})
        assert p.live_streams == frozenset({"live"})

    async def test_start_subscribes_to_buffer(self, presenter: MedianPresenter) -> None:
        """start() subscribes presenter to each device's buffer for that run."""
        presenter.start(make_start("run-1"))  # type: ignore[arg-type]
        assert "run-1" in presenter._subscriptions
        assert len(presenter._subscriptions["run-1"]) == 1

    async def test_scan_descriptor_sets_scan_phase(
        self, presenter: MedianPresenter
    ) -> None:
        """descriptor() for a median_stream sets phase to 'scan'."""
        presenter.start(make_start("run-1"))  # type: ignore[arg-type]
        presenter.descriptor(make_descriptor("d-1", "square_scan", "run-1"))  # type: ignore[arg-type]
        assert presenter._phase["run-1"] == "scan"

    async def test_scan_phase_accumulates_buffer_frames(
        self, presenter: MedianPresenter, mock_buffer_device: MockBufferDevice
    ) -> None:
        """Buffer pushes during scan phase are appended to _frames."""
        presenter.start(make_start("run-1"))  # type: ignore[arg-type]
        presenter.descriptor(make_descriptor("d-1", "square_scan", "run-1"))  # type: ignore[arg-type]

        frame = np.ones((4, 4)) * 3.0
        mock_buffer_device.push_frame(frame)

        frames = presenter._frames["run-1"].get("camera1-buffer", [])
        assert len(frames) == 1
        np.testing.assert_array_equal(frames[0], frame)

    async def test_stream_switch_computes_median(
        self, presenter: MedianPresenter, mock_buffer_device: MockBufferDevice
    ) -> None:
        """descriptor() for live_stream after scan phase computes and stores median."""
        presenter.start(make_start("run-1"))  # type: ignore[arg-type]
        presenter.descriptor(make_descriptor("d-scan", "square_scan", "run-1"))  # type: ignore[arg-type]

        frame = np.ones((4, 4)) * 4.0
        for _ in range(3):
            mock_buffer_device.push_frame(frame.copy())

        presenter.descriptor(make_descriptor("d-live", "live", "run-1"))  # type: ignore[arg-type]

        assert "camera1-buffer" in presenter._medians["run-1"]
        np.testing.assert_array_almost_equal(
            presenter._medians["run-1"]["camera1-buffer"],
            np.ones((4, 4)) * 4.0,
        )
        assert presenter._frames["run-1"] == {}

    async def test_live_phase_emits_corrected_frames(
        self, presenter: MedianPresenter, mock_buffer_device: MockBufferDevice
    ) -> None:
        """Buffer pushes during live phase emit sigNewData with frame / median."""
        presenter.start(make_start("run-1"))  # type: ignore[arg-type]
        presenter.descriptor(make_descriptor("d-scan", "square_scan", "run-1"))  # type: ignore[arg-type]

        median_val = np.ones((4, 4)) * 2.0
        mock_buffer_device.push_frame(median_val.copy())

        presenter.descriptor(make_descriptor("d-live", "live", "run-1"))  # type: ignore[arg-type]

        emitted: list[dict[str, npt.NDArray[np.float64]]] = []
        presenter.sigNewData.connect(lambda d: emitted.append(d))

        live_frame = np.ones((4, 4)) * 6.0
        mock_buffer_device.push_frame(live_frame.copy())

        assert len(emitted) == 1
        result = next(iter(emitted[0].values()))
        np.testing.assert_array_almost_equal(result, np.ones((4, 4)) * 3.0)

    async def test_no_emission_before_median_computed(
        self, presenter: MedianPresenter, mock_buffer_device: MockBufferDevice
    ) -> None:
        """Live buffer push before any scan is a no-op (no median available)."""
        presenter.start(make_start("run-1"))  # type: ignore[arg-type]
        presenter.descriptor(make_descriptor("d-live", "live", "run-1"))  # type: ignore[arg-type]

        emitted: list[object] = []
        presenter.sigNewData.connect(lambda d: emitted.append(d))

        mock_buffer_device.push_frame(np.ones((4, 4)))
        assert emitted == []

    async def test_stop_unsubscribes_buffer(
        self, presenter: MedianPresenter, mock_buffer_device: MockBufferDevice
    ) -> None:
        """stop() removes all subscriptions for that run."""
        presenter.start(make_start("run-1"))  # type: ignore[arg-type]
        presenter.stop(make_stop("run-1"))  # type: ignore[arg-type]

        assert "run-1" not in presenter._subscriptions

        emitted: list[object] = []
        presenter.sigNewData.connect(lambda d: emitted.append(d))
        mock_buffer_device.push_frame(np.ones((4, 4)))
        assert emitted == []

    async def test_stop_one_run_leaves_other_intact(
        self, mock_buffer_device: MockBufferDevice
    ) -> None:
        """stop() for run-2 does not remove run-1's subscriptions or state."""
        presenter = MedianPresenter(
            "p",
            {"camera1": mock_buffer_device},
            median_streams=["square_scan"],
            live_streams=["live"],
        )
        presenter.start(make_start("run-1"))  # type: ignore[arg-type]
        presenter.start(make_start("run-2"))  # type: ignore[arg-type]
        presenter.descriptor(make_descriptor("d1", "square_scan", "run-1"))  # type: ignore[arg-type]

        presenter.stop(make_stop("run-2"))  # type: ignore[arg-type]

        assert "run-1" in presenter._subscriptions
        assert len(presenter._subscriptions["run-1"]) == 1

        mock_buffer_device.push_frame(np.ones((4, 4)) * 5.0)
        assert len(presenter._frames["run-1"].get("camera1-buffer", [])) == 1

    async def test_repeated_stream_cycle_resets_frames(
        self, presenter: MedianPresenter, mock_buffer_device: MockBufferDevice
    ) -> None:
        """A second scan→live cycle uses fresh frames."""
        presenter.start(make_start("run-1"))  # type: ignore[arg-type]

        presenter.descriptor(make_descriptor("d-scan-1", "square_scan", "run-1"))  # type: ignore[arg-type]
        for _ in range(3):
            mock_buffer_device.push_frame(np.ones((4, 4)) * 2.0)

        presenter.descriptor(make_descriptor("d-live-1", "live", "run-1"))  # type: ignore[arg-type]
        first_median = presenter._medians["run-1"]["camera1-buffer"].copy()

        presenter.descriptor(make_descriptor("d-scan-2", "square_scan", "run-1"))  # type: ignore[arg-type]
        for _ in range(2):
            mock_buffer_device.push_frame(np.ones((4, 4)) * 6.0)

        presenter.descriptor(make_descriptor("d-live-2", "live", "run-1"))  # type: ignore[arg-type]
        second_median = presenter._medians["run-1"]["camera1-buffer"]

        np.testing.assert_array_almost_equal(first_median, np.ones((4, 4)) * 2.0)
        np.testing.assert_array_almost_equal(second_median, np.ones((4, 4)) * 6.0)
