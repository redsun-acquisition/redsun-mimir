"""Tests for mock device implementations."""

from __future__ import annotations

import pytest

from redsun_mimir.device._mocks import MockLightDevice
from redsun_mimir.device.mmcore import MMCoreStageDevice, MMCoreXYAxis
from redsun_mimir.protocols import LightProtocol, MotorProtocol


class TestMMCoreStageDevice:
    """Tests for MMCoreStageDevice."""

    async def test_instantiation(self, xy_mock_motor: MMCoreStageDevice) -> None:
        """Device initialises with correct name and two child axes."""
        assert xy_mock_motor.name == "xystage"
        children = dict(xy_mock_motor.children())
        assert set(children) == {"x", "y"}

    async def test_axes_implement_protocol(
        self, xy_mock_motor: MMCoreStageDevice
    ) -> None:
        """Each child axis satisfies MotorProtocol; the container does not."""
        assert isinstance(xy_mock_motor.x, MotorProtocol)  # type: ignore[attr-defined]
        assert isinstance(xy_mock_motor.y, MotorProtocol)  # type: ignore[attr-defined]
        assert not isinstance(xy_mock_motor, MotorProtocol)

    async def test_axes_are_mmcore_xy_axis(
        self, xy_mock_motor: MMCoreStageDevice
    ) -> None:
        """Child axes are MMCoreXYAxis instances."""
        assert isinstance(xy_mock_motor.x, MMCoreXYAxis)  # type: ignore[attr-defined]
        assert isinstance(xy_mock_motor.y, MMCoreXYAxis)  # type: ignore[attr-defined]

    async def test_initial_position_is_zero(
        self, xy_mock_motor: MMCoreStageDevice
    ) -> None:
        """All axes start at position 0."""
        assert await xy_mock_motor.x.position.get_value() == pytest.approx(0.0)  # type: ignore[attr-defined]
        assert await xy_mock_motor.y.position.get_value() == pytest.approx(0.0)  # type: ignore[attr-defined]

    async def test_set_position(self, xy_mock_motor: MMCoreStageDevice) -> None:
        """set() on an axis moves it and updates the position signal."""
        await xy_mock_motor.x.set(5.0)  # type: ignore[attr-defined]
        assert await xy_mock_motor.x.position.get_value() == pytest.approx(5.0)  # type: ignore[attr-defined]

    async def test_set_invalid_value_fails(
        self, xy_mock_motor: MMCoreStageDevice
    ) -> None:
        """set() with a non-numeric value raises."""
        with pytest.raises(Exception):
            await xy_mock_motor.x.set("not_a_number")  # type: ignore[attr-defined, arg-type]

    async def test_step_size_set(self, xy_mock_motor: MMCoreStageDevice) -> None:
        """Step size is updated via the signal."""
        await xy_mock_motor.x.step_size.set(0.5)  # type: ignore[attr-defined]
        assert await xy_mock_motor.x.step_size.get_value() == pytest.approx(0.5)  # type: ignore[attr-defined]

    async def test_read_configuration_contains_step_size(
        self, xy_mock_motor: MMCoreStageDevice
    ) -> None:
        """read_configuration() returns step_size for each axis."""
        cfg = await xy_mock_motor.read_configuration()
        for ax in ["x", "y"]:
            assert f"xystage-{ax}-step_size" in cfg

    async def test_describe_configuration_contains_step_size(
        self, xy_mock_motor: MMCoreStageDevice
    ) -> None:
        """describe_configuration() returns descriptors for each axis signal."""
        desc = await xy_mock_motor.describe_configuration()
        for ax in ["x", "y"]:
            assert f"xystage-{ax}-step_size" in desc

    async def test_axis_children_have_correct_names(
        self, xy_mock_motor: MMCoreStageDevice
    ) -> None:
        """Child axes carry fully-qualified names set by the parent."""
        assert xy_mock_motor.x.name == "xystage-x"  # type: ignore[attr-defined]
        assert xy_mock_motor.y.name == "xystage-y"  # type: ignore[attr-defined]
        assert xy_mock_motor.x.step_size.name == "xystage-x-step_size"  # type: ignore[attr-defined]
        assert xy_mock_motor.x.position.name == "xystage-x-position"  # type: ignore[attr-defined]


class TestMockLightDevice:
    """Tests for MockLightDevice."""

    async def test_binary_instantiation(self, mock_led: MockLightDevice) -> None:
        """Binary LED initialises with correct signal values."""
        assert mock_led.name == "led"
        assert await mock_led.wavelength.get_value() == 450
        assert await mock_led.binary.get_value() is True
        assert await mock_led.enabled.get_value() is False
        assert await mock_led.intensity.get_value() == pytest.approx(0.0)

    async def test_continuous_instantiation(self, mock_laser: MockLightDevice) -> None:
        """Continuous laser initialises with correct signal values."""
        assert mock_laser.name == "laser"
        assert await mock_laser.wavelength.get_value() == 650
        assert await mock_laser.binary.get_value() is False

    async def test_implements_protocol(self, mock_led: MockLightDevice) -> None:
        """MockLightDevice satisfies the LightProtocol runtime check."""
        assert isinstance(mock_led, LightProtocol)

    async def test_trigger_toggles_enabled(self, mock_led: MockLightDevice) -> None:
        """trigger() toggles the enabled state."""
        assert await mock_led.enabled.get_value() is False
        await mock_led.trigger()
        assert await mock_led.enabled.get_value() is True
        await mock_led.trigger()
        assert await mock_led.enabled.get_value() is False

    async def test_set_intensity(self, mock_laser: MockLightDevice) -> None:
        """Setting intensity via the signal updates the value."""
        await mock_laser.intensity.set(42.0)
        assert await mock_laser.intensity.get_value() == pytest.approx(42.0)

    async def test_read_returns_current_state(
        self, mock_laser: MockLightDevice
    ) -> None:
        """read() returns current intensity and enabled state."""
        await mock_laser.intensity.set(10.0)
        reading = await mock_laser.read()
        assert reading["laser-intensity"]["value"] == pytest.approx(10.0)
        assert reading["laser-enabled"]["value"] is False

    async def test_describe_returns_intensity_and_enabled(
        self, mock_laser: MockLightDevice
    ) -> None:
        """describe() includes entries for intensity and enabled."""
        desc = await mock_laser.describe()
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

    async def test_read_configuration_contains_expected_keys(
        self, mock_led: MockLightDevice
    ) -> None:
        """read_configuration() returns wavelength, binary, and step_size."""
        cfg = await mock_led.read_configuration()
        assert "led-wavelength" in cfg
        assert "led-binary" in cfg
        assert "led-step_size" in cfg
        assert cfg["led-wavelength"]["value"] == 450
        assert cfg["led-binary"]["value"] is True

    async def test_describe_configuration_contains_expected_keys(
        self, mock_led: MockLightDevice
    ) -> None:
        """describe_configuration() returns descriptors for all configuration signals."""
        desc = await mock_led.describe_configuration()
        assert "led-wavelength" in desc
        assert "led-binary" in desc
        assert "led-step_size" in desc
