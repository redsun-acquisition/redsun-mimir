"""Tests for mock device implementations."""

from __future__ import annotations

import pytest

from redsun_mimir.device._mocks import MockLightDevice, MockMotorDevice
from redsun_mimir.protocols import LightProtocol, MotorProtocol


class TestMockMotorDevice:
    """Tests for MockMotorDevice."""

    def test_instantiation(self, mock_motor: MockMotorDevice) -> None:
        """Device initialises with correct name and attributes."""
        assert mock_motor.name == "stage"
        assert mock_motor.axis == ["X", "Y", "Z"]
        assert mock_motor.step_sizes == {"X": 1.0, "Y": 1.0, "Z": 1.0}
        assert mock_motor.egu == "um"

    def test_implements_protocol(self, mock_motor: MockMotorDevice) -> None:
        """MockMotorDevice satisfies the MotorProtocol runtime check."""
        assert isinstance(mock_motor, MotorProtocol)

    def test_initial_position_is_zero(self, mock_motor: MockMotorDevice) -> None:
        """All axes start at position 0."""
        loc = mock_motor.locate()
        assert loc["setpoint"] == 0.0
        assert loc["readback"] == 0.0

    def test_set_position(self, mock_motor: MockMotorDevice) -> None:
        """set() moves the motor and updates setpoint and readback."""
        status = mock_motor.set(5.0)
        status.wait(timeout=1.0)
        assert status.success
        loc = mock_motor.locate()
        assert loc["setpoint"] == pytest.approx(5.0)
        assert loc["readback"] == pytest.approx(5.0)

    def test_set_invalid_value_fails(self, mock_motor: MockMotorDevice) -> None:
        """set() with a non-numeric value marks status as failed."""
        status = mock_motor.set("not_a_number")
        with pytest.raises(ValueError):
            status.wait(timeout=1.0)
        assert not status.success

    def test_set_axis_via_prop(self, mock_motor: MockMotorDevice) -> None:
        """Passing prop='axis' switches the active axis."""
        status = mock_motor.set("Y", prop="axis")
        status.wait(timeout=1.0)
        assert status.success
        assert mock_motor._active_axis == "Y"

    def test_set_step_size_via_prop(self, mock_motor: MockMotorDevice) -> None:
        """Passing prop='step_size' updates step size for the active axis."""
        status = mock_motor.set(0.5, prop="step_size")
        status.wait(timeout=1.0)
        assert status.success
        assert mock_motor.step_sizes["X"] == pytest.approx(0.5)

    def test_set_invalid_prop_fails(self, mock_motor: MockMotorDevice) -> None:
        """Passing an unknown prop marks status as failed."""
        status = mock_motor.set(1.0, prop="unknown")
        with pytest.raises(ValueError):
            status.wait(timeout=1.0)
        assert not status.success

    def test_read_configuration_contains_expected_keys(
        self, mock_motor: MockMotorDevice
    ) -> None:
        """read_configuration() returns egu, axis and per-axis step sizes."""
        cfg = mock_motor.read_configuration()
        assert "stage-egu" in cfg
        assert "stage-axis" in cfg
        assert cfg["stage-egu"]["value"] == "um"
        assert cfg["stage-axis"]["value"] == ["X", "Y", "Z"]
        for ax in ["X", "Y", "Z"]:
            key = f"stage-{ax}_step_size"
            assert key in cfg
            assert cfg[key]["value"] == 1.0

    def test_describe_configuration_contains_expected_keys(
        self, mock_motor: MockMotorDevice
    ) -> None:
        """describe_configuration() returns egu, axis and per-axis step size descriptors."""
        desc = mock_motor.describe_configuration()
        assert "stage-egu" in desc
        assert "stage-axis" in desc
        for ax in ["X", "Y", "Z"]:
            assert f"stage-{ax}_step_size" in desc


class TestMockLightDevice:
    """Tests for MockLightDevice."""

    def test_binary_instantiation(self, mock_led: MockLightDevice) -> None:
        """Binary LED initialises with correct attributes."""
        assert mock_led.name == "led"
        assert mock_led.wavelength == 450
        assert mock_led.binary is True
        assert mock_led.enabled is False
        assert mock_led.intensity == pytest.approx(0.0)

    def test_continuous_instantiation(self, mock_laser: MockLightDevice) -> None:
        """Continuous laser initialises with correct attributes."""
        assert mock_laser.name == "laser"
        assert mock_laser.wavelength == 650
        assert mock_laser.binary is False
        assert mock_laser.intensity_range == (0, 100)

    def test_implements_protocol(self, mock_led: MockLightDevice) -> None:
        """MockLightDevice satisfies the LightProtocol runtime check."""
        assert isinstance(mock_led, LightProtocol)

    def test_trigger_toggles_enabled(self, mock_led: MockLightDevice) -> None:
        """trigger() toggles the enabled state."""
        assert mock_led.enabled is False
        status = mock_led.trigger()
        status.wait(timeout=1.0)
        assert status.success
        assert mock_led.enabled is True
        # toggle back
        status = mock_led.trigger()
        status.wait(timeout=1.0)
        assert mock_led.enabled is False

    def test_set_intensity(self, mock_laser: MockLightDevice) -> None:
        """set() updates the intensity."""
        status = mock_laser.set(42.0)
        status.wait(timeout=1.0)
        assert status.success
        assert mock_laser.intensity == pytest.approx(42.0)

    def test_set_invalid_intensity_fails(self, mock_laser: MockLightDevice) -> None:
        """set() with a non-numeric value marks status as failed."""
        status = mock_laser.set("full_power")
        with pytest.raises(ValueError):
            status.wait(timeout=1.0)
        assert not status.success

    def test_read_returns_current_state(self, mock_laser: MockLightDevice) -> None:
        """read() returns current intensity and enabled state."""
        mock_laser.set(10.0).wait(timeout=1.0)
        reading = mock_laser.read()
        assert reading["intensity"]["value"] == pytest.approx(10.0)
        assert reading["enabled"]["value"] is False

    def test_describe_returns_intensity_and_enabled(
        self, mock_laser: MockLightDevice
    ) -> None:
        """describe() includes entries for intensity and enabled."""
        desc = mock_laser.describe()
        assert "intensity" in desc
        assert "enabled" in desc

    def test_invalid_intensity_range_raises(self) -> None:
        """intensity_range with min > max raises AttributeError."""
        with pytest.raises((AttributeError, Exception)):
            MockLightDevice("bad", wavelength=500, intensity_range=(100, 0))

    def test_degenerate_range_on_non_binary_raises(self) -> None:
        """Non-binary device with intensity_range (x, x) raises AttributeError."""
        with pytest.raises((AttributeError, Exception)):
            MockLightDevice("bad", wavelength=500, binary=False, intensity_range=(0, 0))

    def test_read_configuration_contains_expected_keys(
        self, mock_led: MockLightDevice
    ) -> None:
        """read_configuration() returns wavelength, binary, egu, intensity_range, step_size."""
        cfg = mock_led.read_configuration()
        assert "led-wavelength" in cfg
        assert "led-binary" in cfg
        assert "led-egu" in cfg
        assert "led-intensity_range" in cfg
        assert "led-step_size" in cfg
        assert cfg["led-wavelength"]["value"] == 450
        assert cfg["led-binary"]["value"] is True

    def test_describe_configuration_contains_expected_keys(
        self, mock_led: MockLightDevice
    ) -> None:
        """describe_configuration() returns descriptors for all configuration keys."""
        desc = mock_led.describe_configuration()
        assert "led-wavelength" in desc
        assert "led-binary" in desc
        assert "led-egu" in desc
        assert "led-intensity_range" in desc
        assert "led-step_size" in desc
