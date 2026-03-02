"""Tests for mock device implementations."""

from __future__ import annotations

import pytest

from redsun_mimir.device._mocks import MockLightDevice
from redsun_mimir.device.mmcore import MMCoreStageDevice
from redsun_mimir.protocols import LightProtocol, MotorProtocol


class TestMMCoreStageDevice:
    """Tests for MMCoreStageDevice."""

    def test_instantiation(self, xy_mock_motor: MMCoreStageDevice) -> None:
        """Device initialises with correct name and attributes."""
        assert xy_mock_motor.name == "xystage"
        assert xy_mock_motor.axis == ["X", "Y"]
        assert xy_mock_motor.step_sizes == {"X": 0.015, "Y": 0.015}
        assert xy_mock_motor.egu == "um"

    def test_implements_protocol(self, xy_mock_motor: MMCoreStageDevice) -> None:
        """MMCoreStageDevice satisfies the MotorProtocol runtime check."""
        assert isinstance(xy_mock_motor, MotorProtocol)

    def test_initial_position_is_zero(self, xy_mock_motor: MMCoreStageDevice) -> None:
        """All axes start at position 0."""
        loc = xy_mock_motor.locate()
        assert loc["setpoint"] == 0.0
        assert loc["readback"] == 0.0

    def test_set_position(self, xy_mock_motor: MMCoreStageDevice) -> None:
        """set() moves the motor and updates setpoint and readback."""
        status = xy_mock_motor.set(5.0)
        status.wait(timeout=1.0)
        assert status.success
        loc = xy_mock_motor.locate()
        assert loc["setpoint"] == pytest.approx(5.0)
        assert loc["readback"] == pytest.approx(5.0)

    def test_set_invalid_value_fails(self, xy_mock_motor: MMCoreStageDevice) -> None:
        """set() with a non-numeric value marks status as failed."""
        status = xy_mock_motor.set("not_a_number")
        with pytest.raises(TypeError):
            status.wait(timeout=1.0)
        assert not status.success

    def test_set_axis_via_prop(self, xy_mock_motor: MMCoreStageDevice) -> None:
        """Passing prop='axis' switches the active axis."""
        status = xy_mock_motor.set("Y", prop="axis")
        status.wait(timeout=1.0)
        assert status.success
        assert xy_mock_motor._active_axis == "Y"

    def test_set_step_size_via_prop(self, xy_mock_motor: MMCoreStageDevice) -> None:
        """Passing prop='step_size' updates step size for the active axis."""
        status = xy_mock_motor.set(0.5, prop="step_size")
        status.wait(timeout=1.0)
        assert status.success
        assert xy_mock_motor.step_sizes["X"] == pytest.approx(0.5)

    def test_set_invalid_prop_fails(self, xy_mock_motor: MMCoreStageDevice) -> None:
        """Passing an unknown prop marks status as failed."""
        status = xy_mock_motor.set(1.0, prop="unknown")
        with pytest.raises(ValueError):
            status.wait(timeout=1.0)
        assert not status.success

    def test_read_configuration_contains_expected_keys(
        self, xy_mock_motor: MMCoreStageDevice
    ) -> None:
        """read_configuration() returns egu, axis and per-axis step sizes."""
        cfg = xy_mock_motor.read_configuration()
        assert "xystage-egu" in cfg
        assert "xystage-axis" in cfg
        assert cfg["xystage-egu"]["value"] == "um"
        assert cfg["xystage-axis"]["value"] == ["X", "Y"]
        for ax in ["X", "Y"]:
            key = f"xystage-{ax}_step_size"
            assert key in cfg
            assert cfg[key]["value"] == 0.015

    def test_describe_configuration_contains_expected_keys(
        self, xy_mock_motor: MMCoreStageDevice
    ) -> None:
        """describe_configuration() returns egu, axis and per-axis step size descriptors."""
        desc = xy_mock_motor.describe_configuration()
        assert "xystage-egu" in desc
        assert "xystage-axis" in desc
        for ax in ["X", "Y"]:
            assert f"xystage-{ax}_step_size" in desc


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
        assert reading["laser-intensity"]["value"] == pytest.approx(10.0)
        assert reading["laser-enabled"]["value"] is False

    def test_describe_returns_intensity_and_enabled(
        self, mock_laser: MockLightDevice
    ) -> None:
        """describe() includes entries for intensity and enabled."""
        desc = mock_laser.describe()
        assert "laser-intensity" in desc
        assert "laser-enabled" in desc

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
