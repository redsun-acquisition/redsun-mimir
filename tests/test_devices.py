"""Tests for mock device implementations."""

from __future__ import annotations

import pytest

from redsun_mimir.device._mocks import MockLightDevice
from redsun_mimir.device.mmcore import MMDemoXYStage
from redsun_mimir.protocols import LightProtocol


class TestMMDemoXYStage:
    """Tests for MMDemoXYStage."""

    async def test_instantiation(self, xy_mock_motor: MMDemoXYStage) -> None:
        """Device initialises with correct name and children."""
        assert xy_mock_motor.name == "xystage"
        children = dict(xy_mock_motor.children())
        assert set(children) == {"axis", "x", "y"}

    async def test_initial_position_is_zero(
        self, xy_mock_motor: MMDemoXYStage
    ) -> None:
        """All axes start at position 0."""
        assert await xy_mock_motor.x.get_value() == pytest.approx(0.0)
        assert await xy_mock_motor.y.get_value() == pytest.approx(0.0)

    async def test_set_position(self, xy_mock_motor: MMDemoXYStage) -> None:
        """set() on an axis changes the position readback."""
        initial = await xy_mock_motor.x.get_value()
        target = initial + 5.0
        await xy_mock_motor.x.set(target)
        after = await xy_mock_motor.x.get_value()
        assert after != pytest.approx(initial), "Position should have changed"

    async def test_set_invalid_value_fails(
        self, xy_mock_motor: MMDemoXYStage
    ) -> None:
        """set() with a non-numeric value raises."""
        with pytest.raises(Exception):
            await xy_mock_motor.x.set("not_a_number")  # type: ignore[arg-type]

    async def test_axis_children_have_correct_names(
        self, xy_mock_motor: MMDemoXYStage
    ) -> None:
        """Child axes carry fully-qualified names set by the parent."""
        assert xy_mock_motor.x.name == "xystage-axis-x"
        assert xy_mock_motor.y.name == "xystage-axis-y"

    async def test_axis_device_map_has_axes(
        self, xy_mock_motor: MMDemoXYStage
    ) -> None:
        """The axis DeviceMap contains x and y signals."""
        assert "x" in xy_mock_motor.axis
        assert "y" in xy_mock_motor.axis
        assert xy_mock_motor.axis["x"] is xy_mock_motor.x
        assert xy_mock_motor.axis["y"] is xy_mock_motor.y


class TestMockLightDevice:
    """Tests for MockLightDevice."""

    async def test_binary_instantiation(self, mock_led: MockLightDevice) -> None:
        """LED initialises with correct signal values."""
        assert mock_led.name == "led"
        assert await mock_led.wavelength.get_value() == 450
        assert await mock_led.enabled.get_value() is False
        assert await mock_led.intensity.get_value() == pytest.approx(0.0)

    async def test_continuous_instantiation(self, mock_laser: MockLightDevice) -> None:
        """Laser initialises with correct signal values."""
        assert mock_laser.name == "laser"
        assert await mock_laser.wavelength.get_value() == 650

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
        """intensity_range - invalid range raises."""
        with pytest.raises(ValueError):
            MockLightDevice("bad", wavelength=500, range=[100.0, 0.0])

    def test_degenerate_range_raises(self) -> None:
        """range with equal low and high values raises ValueError."""
        with pytest.raises(ValueError):
            MockLightDevice("bad", wavelength=500, range=[0.0, 0.0])

    async def test_read_configuration_contains_expected_keys(
        self, mock_led: MockLightDevice
    ) -> None:
        """read_configuration() returns wavelength."""
        cfg = await mock_led.read_configuration()
        assert "led-wavelength" in cfg
        assert cfg["led-wavelength"]["value"] == 450

    async def test_describe_configuration_contains_expected_keys(
        self, mock_led: MockLightDevice
    ) -> None:
        """describe_configuration() returns descriptors for all configuration signals."""
        desc = await mock_led.describe_configuration()
        assert "led-wavelength" in desc
