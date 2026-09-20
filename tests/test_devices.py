"""Tests for mock device implementations."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from redsun_mimir.device._mocks import MockLightDevice
from redsun_mimir.device.mmcore import MMStage
from redsun_mimir.device.mmcore._stage import POSITION_TOLERANCE
from redsun_mimir.device.youseetoo import UC2LaserDevice
from redsun_mimir.presenter.light import LightPresenter
from redsun_mimir.presenter.motor import MotorPresenter
from redsun_mimir.protocols import LightProtocol, MotorProtocol
from tests.conftest import CONNECT_TIMEOUT, needs_mm_adapters

if TYPE_CHECKING:
    from redsun.services import Service


class TestMMStage:
    """The stage as a session sees it: through the service that owns it.

    The axes come from the served PVI tree and live only inside the ``axis``
    map, so readings are keyed ``<device>-axis-<name>``, which is what
    redsun's ``parse_map_key(key, "axis")`` (used by ``MotorView``) splits.
    """

    @needs_mm_adapters
    async def test_axes_are_exposed_and_readable(self, mm_stage: MMStage) -> None:
        """The stage takes its axes from what the service serves."""
        assert set(mm_stage.axis) == {"x", "y"}
        assert isinstance(mm_stage, MotorProtocol)

        readings = await mm_stage.read()
        assert set(readings) == {"XY-axis-x", "XY-axis-y"}
        assert set(await mm_stage.describe()) == set(readings)
        assert mm_stage.axis["x"].parent is mm_stage.axis

    @needs_mm_adapters
    async def test_set_waits_for_the_axis_to_arrive(self, mm_stage: MMStage) -> None:
        """``set`` completes once the stage has travelled, within tolerance.

        The demo stage simulates motion and settles on its own grid, landing
        within ~0.006 um of any request. `MovableLogic`'s default waits for
        the readback to equal the setpoint exactly, which would never happen;
        `MMAxisLogic` waits within `POSITION_TOLERANCE`, so without that
        override this test hangs rather than fails.
        """
        await asyncio.wait_for(mm_stage.axis["x"].set(10.0), timeout=10.0)

        location = await mm_stage.axis["x"].locate()
        assert location["readback"] == pytest.approx(10.0, abs=POSITION_TOLERANCE)
        assert (await mm_stage.read())["XY-axis-x"]["value"] == pytest.approx(
            10.0, abs=POSITION_TOLERANCE
        )


class TestUC2LaserDevice:
    """The UC2 laser as the light presenter sees it."""

    async def test_the_laser_satisfies_the_light_protocol(
        self, uc2_service: Service
    ) -> None:
        """Without every member, the presenter drops the device in silence."""
        laser = UC2LaserDevice(uc2_service.prefix, wavelength=650, name="laser")
        await laser.connect(timeout=CONNECT_TIMEOUT)

        assert isinstance(laser, LightProtocol)
        assert await laser.binary.get_value() is False

        presenter = LightPresenter("light_ctrl", {laser.name: laser})
        try:
            assert f"{laser.name}-intensity" in presenter.device_description()
        finally:
            presenter.shutdown()


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
class TestMMStageConcurrency:
    """A Micro-Manager XY stage writes both coordinates on every set.

    The service reads the pair and writes the pair, so two moves in flight on
    sibling axes each carry the other's pre-move value unless the service
    serialises them. Only a real stage reproduces this: a soft-signal double
    has no setter at all.
    """

    @needs_mm_adapters
    async def test_moving_both_axes_at_once_moves_both(self, mm_stage: MMStage) -> None:
        """The service serialises, so neither move carries a stale sibling.

        Without that, a move whose sibling reverts it never reaches its
        setpoint and the wait never returns, so this is bounded.
        """
        await asyncio.wait_for(
            asyncio.gather(mm_stage.axis["x"].set(10.0), mm_stage.axis["y"].set(10.0)),
            timeout=30.0,
        )

        assert (await mm_stage.axis["x"].locate())["readback"] == pytest.approx(
            10.0, abs=0.1
        )
        assert (await mm_stage.axis["y"].locate())["readback"] == pytest.approx(
            10.0, abs=0.1
        )

    @needs_mm_adapters
    async def test_stepping_both_axes_moves_both(self, mm_stage: MMStage) -> None:
        """Without serialising, the second write reverts the first axis."""
        stage = mm_stage
        presenter = MotorPresenter("motor_ctrl", {stage.name: stage})
        try:
            await asyncio.gather(
                presenter.move(stage.name, "x", 10.0),
                presenter.move(stage.name, "y", 10.0),
            )

            # the demo stage snaps to its own grid, so compare loosely: the
            # point is that neither axis was left behind, not the exact stop
            assert (await stage.axis["x"].locate())["readback"] == pytest.approx(
                10.0, abs=0.1
            )
            assert (await stage.axis["y"].locate())["readback"] == pytest.approx(
                10.0, abs=0.1
            )
        finally:
            presenter.shutdown()
