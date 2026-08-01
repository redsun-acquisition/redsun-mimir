"""Tests for mock device implementations."""

from __future__ import annotations

import asyncio

import pytest

from redsun_mimir.device._mocks import MockLightDevice
from redsun_mimir.device.mmcore import MMDemoXYStage, MMDemoZStage
from redsun_mimir.presenter.motor import MotorPresenter
from redsun_mimir.protocols import LightProtocol, MotorProtocol
from tests.conftest import needs_mm_adapters


class TestMMDemoStage:
    """Tests for the Micro-Manager demo stages.

    The axis signals live only inside the ``axis`` ``DeviceMap`` - binding
    them as attributes first would parent them to the stage, and ophyd-async
    refuses to re-parent a ``Device`` into the map. Readings must therefore
    be keyed ``<device>-axis-<name>``, which is what redsun's
    ``parse_map_key(key, "axis")`` (used by ``MotorView``) splits.
    """

    @pytest.mark.parametrize(
        ("cls", "expected_axes"),
        [
            pytest.param(MMDemoXYStage, {"x", "y"}, id="xy-stage"),
            pytest.param(MMDemoZStage, {"z"}, id="z-stage"),
        ],
    )
    async def test_axes_are_exposed_and_readable(
        self,
        cls: type[MMDemoXYStage | MMDemoZStage],
        expected_axes: set[str],
    ) -> None:
        device = cls("stage")
        await device.connect(mock=True)

        assert set(device.axis.keys()) == expected_axes
        assert isinstance(device, MotorProtocol)

        readings = await device.read()
        assert set(readings) == {f"stage-axis-{axis}" for axis in expected_axes}
        assert set(await device.describe()) == set(readings)

    async def test_axis_signals_are_not_bound_as_attributes(self) -> None:
        """Binding the signals on the device too would break construction."""
        device = MMDemoXYStage("stage")
        await device.connect(mock=True)

        assert not hasattr(device, "x")
        assert device.axis["x"].parent is device.axis

    async def test_set_waits_for_the_axis_to_arrive(self) -> None:
        """``set`` completes only once the stage has actually travelled.

        The Micro-Manager demo stage simulates motion, so a set that returned
        immediately would leave the axis in transit - and a scan reading a
        frame straight after the move would capture the wrong position.
        Note the signals are callable-backed soft signals: ``mock=True`` does
        not isolate them, this really drives the demo adapter.
        """
        device = MMDemoXYStage("stage")
        await device.connect(mock=True)

        await device.axis["x"].set(12.5)
        assert await device.axis["x"].get_value() == pytest.approx(12.5, abs=0.05)


class TestMockLightDevice:
    """Tests for MockLightDevice."""

    @pytest.mark.parametrize(
        ("wavelength", "range_"),
        [
            pytest.param(450, (0.0, 1.0), id="narrow-range"),
            pytest.param(650, (0.0, 100.0), id="wide-range"),
        ],
    )
    async def test_instantiation(
        self, wavelength: int, range_: tuple[float, float]
    ) -> None:
        """Device initialises with the requested wavelength and starts off/at zero."""
        device = MockLightDevice("light", wavelength=wavelength, range=range_)
        await device.connect(mock=True)
        assert device.name == "light"
        assert await device.wavelength.get_value() == wavelength
        assert await device.enabled.get_value() is False
        assert await device.intensity.get_value() == pytest.approx(0.0)

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

    @pytest.mark.parametrize(
        ("range_", "match"),
        [
            pytest.param(
                (0.0,), "Range must be a list of two floats", id="wrong-length"
            ),
            pytest.param(
                (100.0, 0.0), "low value must be less than high", id="low-gt-high"
            ),
            pytest.param(
                (5.0, 5.0), "low value must be less than high", id="degenerate"
            ),
        ],
    )
    def test_invalid_range_raises(self, range_: tuple[float, ...], match: str) -> None:
        """An invalid range raises ValueError with a specific message."""
        with pytest.raises(ValueError, match=match):
            MockLightDevice("bad", wavelength=500, range=range_)  # type: ignore[arg-type]

    async def test_read_configuration_contains_wavelength(
        self, mock_led: MockLightDevice
    ) -> None:
        """read_configuration() returns the wavelength."""
        cfg = await mock_led.read_configuration()
        assert cfg["led-wavelength"]["value"] == 450

    async def test_describe_configuration_contains_wavelength(
        self, mock_led: MockLightDevice
    ) -> None:
        """describe_configuration() returns a descriptor for wavelength."""
        desc = await mock_led.describe_configuration()
        assert "led-wavelength" in desc


@needs_mm_adapters
class TestMMDemoStageConcurrency:
    """A Micro-Manager XY stage writes both coordinates on every set.

    ``mm_position_signal``'s setter reads the pair and writes the pair, so two
    sets in flight on sibling axes each carry the other's pre-move value. Only
    a real stage reproduces this: the soft-signal double has no setter at all.
    """

    async def test_stepping_both_axes_moves_both(self) -> None:
        """Without a per-device lock the second write reverts the first axis."""
        stage = MMDemoXYStage("xystage")
        await stage.connect()
        presenter = MotorPresenter("motor_ctrl", {"xystage": stage})
        try:
            await asyncio.gather(
                presenter.move("xystage", "x", 10.0),
                presenter.move("xystage", "y", 10.0),
            )

            # the demo stage snaps to its own grid, so compare loosely: the
            # point is that neither axis was left behind, not the exact stop
            assert await stage.axis["x"].get_value() == pytest.approx(10.0, abs=0.1)
            assert await stage.axis["y"].get_value() == pytest.approx(10.0, abs=0.1)
        finally:
            presenter.shutdown()
