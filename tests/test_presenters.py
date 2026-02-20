"""Tests for presenter implementations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Generator

import numpy as np
import pytest
from dependency_injector import providers
from dependency_injector.containers import DynamicContainer
from sunflare.virtual import VirtualContainer

from redsun_mimir.device._mocks import MockLightDevice, MockMotorDevice
from redsun_mimir.presenter._light import LightPresenter
from redsun_mimir.presenter._median import MedianPresenter
from redsun_mimir.presenter._motor import MotorPresenter


def _make_di_container(**objects: Any) -> DynamicContainer:
    """Build a minimal DynamicContainer seeded with Object providers."""
    container = DynamicContainer()
    for name, value in objects.items():
        setattr(container, name, providers.Object(value))
    return container


class TestMotorPresenter:
    """Tests for MotorPresenter presenter."""

    @pytest.fixture
    def devices(self, mock_motor: MockMotorDevice) -> dict[str, MockMotorDevice]:
        return {"stage": mock_motor}

    @pytest.fixture
    def controller(
        self, devices: dict[str, MockMotorDevice], virtual_container: VirtualContainer
    ) -> Generator[MotorPresenter, None, None]:
        ctrl = MotorPresenter("motor_presenter", devices)
        yield ctrl
        ctrl.shutdown()

    def test_instantiation(self, controller: MotorPresenter) -> None:
        """Controller initialises and identifies motor devices."""
        assert "stage" in controller._motors

    def test_register_providers(
        self, controller: MotorPresenter, virtual_container: VirtualContainer
    ) -> None:
        """register_providers() populates motor_configuration on the container."""
        controller.register_providers(virtual_container)
        assert hasattr(virtual_container, "motor_configuration")
        cfg = virtual_container.motor_configuration()
        assert any("stage" in k for k in cfg)

    def test_move_updates_position(
        self, controller: MotorPresenter, mock_motor: MockMotorDevice
    ) -> None:
        """move() enqueues and executes a position update."""
        received: list[tuple[str, str, float]] = []
        controller.sigNewPosition.connect(lambda m, a, p: received.append((m, a, p)))
        controller.move("stage", "X", 10.0)
        # Drain the daemon queue
        controller._queue.join()
        assert len(received) == 1
        motor_name, axis, pos = received[0]
        assert motor_name == "stage"
        assert axis == "X"
        assert pos == pytest.approx(10.0)
        assert mock_motor.locate()["setpoint"] == pytest.approx(10.0)

    def test_move_via_device_name(
        self, controller: MotorPresenter, mock_motor: MockMotorDevice
    ) -> None:
        """move() accepts the bare device name."""
        controller.move(mock_motor.name, "X", 5.0)
        controller._queue.join()
        assert mock_motor.locate()["setpoint"] == pytest.approx(5.0)

    def test_configure_step_size(
        self, controller: MotorPresenter, mock_motor: MockMotorDevice
    ) -> None:
        """configure() updates the step size and emits sigNewConfiguration."""
        received: list[tuple[str, dict[str, bool]]] = []
        controller.sigNewConfiguration.connect(lambda m, r: received.append((m, r)))
        step_key = "stage\\X_step_size"
        result = controller.configure("stage", {step_key: 0.5})
        assert result.get(step_key) is True
        assert mock_motor.step_sizes["X"] == pytest.approx(0.5)
        assert len(received) == 1

    def test_configure_via_device_name(
        self, controller: MotorPresenter, mock_motor: MockMotorDevice
    ) -> None:
        """configure() accepts the bare device name."""
        step_key = f"{mock_motor.name}\\X_step_size"
        result = controller.configure(mock_motor.name, {step_key: 2.0})
        assert result.get(step_key) is True
        assert mock_motor.step_sizes["X"] == pytest.approx(2.0)

    def test_shutdown_stops_daemon(self, controller: MotorPresenter) -> None:
        """shutdown() terminates the background thread gracefully."""
        controller.shutdown()
        controller._daemon.join(timeout=2.0)
        assert not controller._daemon.is_alive()


# ---------------------------------------------------------------------------
# LightPresenter
# ---------------------------------------------------------------------------


class TestLightPresenter:
    """Tests for LightPresenter presenter."""

    @pytest.fixture
    def devices(
        self, mock_led: MockLightDevice, mock_laser: MockLightDevice
    ) -> dict[str, MockLightDevice]:
        return {"led": mock_led, "laser": mock_laser}

    @pytest.fixture
    def controller(
        self, devices: dict[str, MockLightDevice], virtual_container: VirtualContainer
    ) -> LightPresenter:
        return LightPresenter("light_presenter", devices)

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
        self, controller: LightPresenter, mock_led: MockLightDevice
    ) -> None:
        """trigger() toggles the target light source."""
        assert mock_led.enabled is False
        controller.trigger("led")
        assert mock_led.enabled is True
        controller.trigger("led")
        assert mock_led.enabled is False

    def test_trigger_via_device_name(
        self, controller: LightPresenter, mock_led: MockLightDevice
    ) -> None:
        """trigger() accepts the bare device name."""
        assert mock_led.enabled is False
        controller.trigger(mock_led.name)
        assert mock_led.enabled is True

    def test_set_intensity(
        self, controller: LightPresenter, mock_laser: MockLightDevice
    ) -> None:
        """set() updates the intensity of the target light source."""
        controller.set("laser", 75.0)
        assert mock_laser.intensity == pytest.approx(75.0)

    def test_set_intensity_via_device_name(
        self, controller: LightPresenter, mock_laser: MockLightDevice
    ) -> None:
        """set() accepts the bare device name."""
        controller.set(mock_laser.name, 42.0)
        assert mock_laser.intensity == pytest.approx(42.0)

    def test_non_light_devices_are_excluded(
        self, mock_motor: MockMotorDevice, virtual_container: VirtualContainer
    ) -> None:
        """MotorDevice is not included in _lights even if passed in devices."""
        devices: dict[str, Any] = {"motor": mock_motor}
        ctrl = LightPresenter("light_presenter", devices)
        assert "motor" not in ctrl._lights


# ---------------------------------------------------------------------------
# MedianPresenter
# ---------------------------------------------------------------------------


class TestMedianPresenter:
    """Tests for MedianPresenter."""

    @pytest.fixture
    def presenter(self, virtual_container: VirtualContainer) -> MedianPresenter:
        return MedianPresenter(
            "median_presenter", {}, streams=["square_scan"], hints=["buffer"]
        )

    def _make_event(self, descriptor_uid: str, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "descriptor": descriptor_uid,
            "data": data,
            "timestamps": {k: 0.0 for k in data},
            "seq_num": 1,
            "uid": "evt-uid",
            "time": 0.0,
        }

    def _make_descriptor(self, uid: str, name: str) -> dict[str, Any]:
        return {
            "uid": uid,
            "name": name,
            "run_start": "run-uid",
            "data_keys": {},
            "time": 0.0,
            "configuration": {},
            "hints": {},
            "object_keys": {},
        }

    def test_instantiation(self, presenter: MedianPresenter) -> None:
        """Presenter initialises with empty state."""
        assert presenter.median_stacks == {}
        assert presenter.medians == {}

    def test_start_clears_state(self, presenter: MedianPresenter) -> None:
        """start() resets all cached data."""
        presenter.median_stacks["obj"] = {"buffer": [np.zeros((4, 4))]}
        start_doc: dict[str, Any] = {
            "uid": "run-uid",
            "time": 0.0,
            "hints": {},
            "plan_name": "test",
        }
        presenter.start(start_doc)  # type: ignore[arg-type]
        assert presenter.median_stacks == {}
        assert presenter.medians == {}

    def test_descriptor_stores_stream_name(self, presenter: MedianPresenter) -> None:
        """descriptor() maps UID to stream name."""
        doc = self._make_descriptor("desc-uid", "square_scan")
        presenter.descriptor(doc)  # type: ignore[arg-type]
        assert presenter.uid_to_stream["desc-uid"] == "square_scan"

    def test_expected_stream_stacks_data(self, presenter: MedianPresenter) -> None:
        """Events from an expected stream are stacked, not emitted."""
        desc_uid = "desc-1"
        presenter.uid_to_stream[desc_uid] = "square_scan"

        frame = np.ones((4, 4))
        evt = self._make_event(desc_uid, {"cam\\buffer": frame})

        emitted: list[Any] = []
        presenter.sigNewData.connect(lambda d: emitted.append(d))

        presenter.event(evt)  # type: ignore[arg-type]

        # Data should be stacked, not emitted yet
        assert "cam" in presenter.median_stacks
        assert len(presenter.median_stacks["cam"]["buffer"]) == 1
        assert emitted == []

    def test_non_expected_stream_computes_and_emits_median(
        self, presenter: MedianPresenter
    ) -> None:
        """Events from a non-expected stream trigger median computation and emission."""
        scan_uid = "scan-desc"
        live_uid = "live-desc"
        presenter.uid_to_stream[scan_uid] = "square_scan"
        presenter.uid_to_stream[live_uid] = "primary"

        # Stack two identical frames so median == the frame itself
        frame = np.ones((4, 4)) * 2.0
        for _ in range(2):
            presenter.event(self._make_event(scan_uid, {"cam\\buffer": frame}))  # type: ignore[arg-type]

        # Now send a live event — median should be applied
        emitted: list[Any] = []
        presenter.sigNewData.connect(lambda d: emitted.append(d))

        live_frame = np.ones((4, 4)) * 4.0
        presenter.event(self._make_event(live_uid, {"cam\\buffer": live_frame}))  # type: ignore[arg-type]

        assert len(emitted) == 1
        result = emitted[0]
        # cam-median key should be present
        assert any("median" in k for k in result)
