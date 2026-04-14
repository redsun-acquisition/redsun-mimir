"""Tests for mock device implementations."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
import pytest
from redsun.device import SoftAttrR

from redsun_mimir.device._mocks import MockLightDevice
from redsun_mimir.device.mmcore import MMCoreStageDevice, MMCoreXYAxis
from redsun_mimir.protocols import DetectorProtocol, LightProtocol, MotorProtocol


class TestMMCoreStageDevice:
    """Tests for MMCoreStageDevice."""

    def test_instantiation(self, xy_mock_motor: MMCoreStageDevice) -> None:
        """Device initialises with correct name and two child axes."""
        assert xy_mock_motor.name == "xystage"
        children = dict(xy_mock_motor.children())
        assert set(children) == {"x", "y"}

    def test_axes_implement_protocol(self, xy_mock_motor: MMCoreStageDevice) -> None:
        """Each child axis satisfies MotorProtocol; the container does not."""
        assert isinstance(xy_mock_motor.x, MotorProtocol)  # type: ignore[attr-defined]
        assert isinstance(xy_mock_motor.y, MotorProtocol)  # type: ignore[attr-defined]
        assert not isinstance(xy_mock_motor, MotorProtocol)

    def test_axes_are_mmcore_xy_axis(self, xy_mock_motor: MMCoreStageDevice) -> None:
        """Child axes are MMCoreXYAxis instances."""
        assert isinstance(xy_mock_motor.x, MMCoreXYAxis)  # type: ignore[attr-defined]
        assert isinstance(xy_mock_motor.y, MMCoreXYAxis)  # type: ignore[attr-defined]

    def test_initial_position_is_zero(self, xy_mock_motor: MMCoreStageDevice) -> None:
        """All axes start at position 0."""
        loc = xy_mock_motor.x.locate()  # type: ignore[attr-defined]
        assert loc["setpoint"] == 0.0
        assert loc["readback"] == 0.0

    def test_set_position(self, xy_mock_motor: MMCoreStageDevice) -> None:
        """set() on an axis moves it and updates setpoint and readback."""
        status = xy_mock_motor.x.set(5.0)  # type: ignore[attr-defined]
        status.wait(timeout=1.0)
        assert status.success
        loc = xy_mock_motor.x.locate()  # type: ignore[attr-defined]
        assert loc["setpoint"] == pytest.approx(5.0)
        assert loc["readback"] == pytest.approx(5.0)

    def test_set_invalid_value_fails(self, xy_mock_motor: MMCoreStageDevice) -> None:
        """set() with a non-numeric value marks status as failed."""
        status = xy_mock_motor.x.set("not_a_number")  # type: ignore[attr-defined, arg-type]
        with pytest.raises(Exception):
            status.wait(timeout=1.0)
        assert not status.success

    def test_step_size_set_directly(self, xy_mock_motor: MMCoreStageDevice) -> None:
        """Step size is updated directly on the axis."""
        xy_mock_motor.x.step_size.set(0.5)  # type: ignore[attr-defined]
        assert xy_mock_motor.x.step_size.get_value() == pytest.approx(0.5)  # type: ignore[attr-defined]

    def test_read_configuration_contains_expected_keys(
        self, xy_mock_motor: MMCoreStageDevice
    ) -> None:
        """read_configuration() returns position and step_size for each axis."""
        cfg = xy_mock_motor.read_configuration()
        for ax in ["x", "y"]:
            assert f"xystage-{ax}-position" in cfg
            assert f"xystage-{ax}-step_size" in cfg
        assert cfg["xystage-x-step_size"]["value"] == pytest.approx(0.015)

    def test_describe_configuration_contains_expected_keys(
        self, xy_mock_motor: MMCoreStageDevice
    ) -> None:
        """describe_configuration() returns descriptors for each axis signal."""
        desc = xy_mock_motor.describe_configuration()
        for ax in ["x", "y"]:
            assert f"xystage-{ax}-position" in desc
            assert f"xystage-{ax}-step_size" in desc

    def test_axis_children_have_correct_names(
        self, xy_mock_motor: MMCoreStageDevice
    ) -> None:
        """Child axes carry fully-qualified names injected by set_name."""
        assert xy_mock_motor.x.name == "xystage-x"  # type: ignore[attr-defined]
        assert xy_mock_motor.y.name == "xystage-y"  # type: ignore[attr-defined]
        assert xy_mock_motor.x.step_size.name == "xystage-x-step_size"  # type: ignore[attr-defined]
        assert xy_mock_motor.x.position.name == "xystage-x-position"  # type: ignore[attr-defined]


class TestMockLightDevice:
    """Tests for MockLightDevice."""

    def test_binary_instantiation(self, mock_led: MockLightDevice) -> None:
        """Binary LED initialises with correct attributes."""
        assert mock_led.name == "led"
        assert mock_led.wavelength == 450
        assert mock_led.binary is True
        assert mock_led.enabled.get_value() is False
        assert mock_led.intensity.get_value() == pytest.approx(0.0)

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
        assert mock_led.enabled.get_value() is False
        status = mock_led.trigger()
        status.wait(timeout=1.0)
        assert status.success
        assert mock_led.enabled.get_value() is True
        # toggle back
        status = mock_led.trigger()
        status.wait(timeout=1.0)
        assert mock_led.enabled.get_value() is False

    def test_set_intensity(self, mock_laser: MockLightDevice) -> None:
        """set() updates the intensity."""
        status = mock_laser.set(42.0)
        status.wait(timeout=1.0)
        assert status.success
        assert mock_laser.intensity.get_value() == pytest.approx(42.0)

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


class TestDetectorProtocol:
    """Structural tests for DetectorProtocol."""

    def test_buffer_attribute_required(self) -> None:
        """DetectorProtocol requires a buffer attribute satisfying AttrR."""

        class MinimalDetector:
            name = "cam"
            parent = None
            roi: tuple[int, int, int, int] = (0, 0, 512, 512)
            sensor_shape: tuple[int, int] = (512, 512)
            buffer = SoftAttrR[npt.NDArray[np.uint16]](
                np.zeros((512, 512), dtype=np.uint16),
                name="cam-buffer",
            )

            def set(self, value: object, **kwargs: object) -> object: ...
            def read(self) -> dict[str, object]:
                return {}

            def describe(self) -> dict[str, object]:
                return {}

            def stage(self) -> object: ...
            def unstage(self) -> object: ...
            def describe_configuration(self) -> dict[str, object]:
                return {}

            def read_configuration(self) -> dict[str, object]:
                return {}

            def set_name(self, name: str, **kwargs: object) -> None: ...

        assert isinstance(MinimalDetector(), DetectorProtocol)

    def test_missing_buffer_fails_protocol(self) -> None:
        """A class without buffer does not satisfy DetectorProtocol."""

        class NobufferDetector:
            name = "cam"
            parent = None
            roi: tuple[int, int, int, int] = (0, 0, 512, 512)
            sensor_shape: tuple[int, int] = (512, 512)

            def set(self, value: object, **kwargs: object) -> object: ...
            def read(self) -> dict[str, object]:
                return {}

            def describe(self) -> dict[str, object]:
                return {}

            def stage(self) -> object: ...
            def unstage(self) -> object: ...
            def describe_configuration(self) -> dict[str, object]:
                return {}

            def read_configuration(self) -> dict[str, object]:
                return {}

            def set_name(self, name: str, **kwargs: object) -> None: ...

        assert not isinstance(NobufferDetector(), DetectorProtocol)
