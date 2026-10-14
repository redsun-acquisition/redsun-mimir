"""Tests for mock device implementations."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from redsun_mimir.device._mocks import MockLightDevice
from redsun_mimir.device.mmcore import MMStage
from redsun_mimir.device.mmcore._stage import MOVE_TIMEOUT, POSITION_TOLERANCE
from redsun_mimir.device.youseetoo import UC2LaserDevice
from redsun_mimir.protocols import MotorProtocol
from tests.conftest import CONNECT_TIMEOUT, needs_mm_adapters

if TYPE_CHECKING:
    from redsun.services import Service


@needs_mm_adapters
class TestMMStage:
    """The stage as a session sees it: through the service that owns it."""

    async def test_axes_are_exposed_and_readable(self, mm_stage: MMStage) -> None:
        """Take the axes from what the service serves, keyed `<device>-axis-<name>`."""
        assert set(mm_stage.axis) == {"x", "y"}
        assert isinstance(mm_stage, MotorProtocol)

        readings = await mm_stage.read()
        assert set(readings) == {"XY-axis-x", "XY-axis-y"}
        assert set(await mm_stage.describe()) == set(readings)
        assert mm_stage.axis["x"].parent is mm_stage.axis

    async def test_set_waits_for_the_axis_to_arrive(self, mm_stage: MMStage) -> None:
        """Complete `set` once the stage has travelled to within the tolerance."""
        # the demo stage settles on its own grid, never exactly on the setpoint,
        # so a wait for an exact match would hang until the timeout
        await asyncio.wait_for(mm_stage.axis["x"].set(10.0), timeout=10.0)

        location = await mm_stage.axis["x"].locate()
        assert location["readback"] == pytest.approx(10.0, abs=POSITION_TOLERANCE)
        assert (await mm_stage.read())["XY-axis-x"]["value"] == pytest.approx(
            10.0, abs=POSITION_TOLERANCE
        )

    async def test_relative_moves_off_the_grid_all_arrive(
        self, mm_stage: MMStage
    ) -> None:
        """Arrive at every relative move, though each target drifts off the grid."""
        # the service reports two decimals: the ninth 5 um step from zero reads
        # a full 0.01 um from its target
        x = mm_stage.axis["x"]
        for _ in range(12):
            target = (await x.locate())["readback"] + 5.0
            await asyncio.wait_for(x.set(target), timeout=MOVE_TIMEOUT + 1)
            assert (await x.locate())["readback"] == pytest.approx(
                target, abs=POSITION_TOLERANCE
            )


class TestUC2LaserDevice:
    """The UC2 laser, switched through the intensity its board knows."""

    async def test_the_switch_lights_and_darkens_the_board(
        self, uc2_service: Service
    ) -> None:
        """Switch off to 0 and back on to the intensity the laser had."""
        laser = UC2LaserDevice(uc2_service.prefix, wavelength=650, name="laser")
        await laser.connect(timeout=CONNECT_TIMEOUT)

        await laser.intensity.set(500)
        assert await laser.enabled.get_value() is True

        await laser.enabled.set(False)
        assert await laser.intensity.get_value() == 0
        assert await laser.enabled.get_value() is False

        await laser.enabled.set(True)
        assert await laser.intensity.get_value() == 500

    async def test_turning_on_keeps_an_intensity_set_while_off(
        self, uc2_service: Service
    ) -> None:
        """Keep an intensity set while off, since it lit the laser already."""
        laser = UC2LaserDevice(uc2_service.prefix, wavelength=650, name="laser")
        await laser.connect(timeout=CONNECT_TIMEOUT)
        await laser.intensity.set(500)
        await laser.enabled.set(False)

        await laser.intensity.set(200)
        await laser.enabled.set(True)

        assert await laser.intensity.get_value() == 200

    async def test_a_laser_never_lit_stays_off(self, uc2_service: Service) -> None:
        """Leave the laser off when there is no intensity to restore."""
        laser = UC2LaserDevice(uc2_service.prefix, wavelength=650, name="laser")
        await laser.connect(timeout=CONNECT_TIMEOUT)

        await laser.enabled.set(True)

        assert await laser.enabled.get_value() is False


class TestMockLightDevice:
    """Tests for MockLightDevice."""

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
        """Refuse a range that is not two increasing bounds."""
        with pytest.raises(ValueError, match=match):
            MockLightDevice("bad", wavelength=500, range=range_)  # type: ignore[arg-type]


@needs_mm_adapters
class TestMMStageConcurrency:
    """A Micro-Manager XY stage writes both coordinates on every set.

    The service reads the pair and writes the pair, so two moves in flight on
    sibling axes each carry the other's pre-move value unless the service
    serialises them. Only a real stage reproduces this: a soft-signal double
    has no setter at all.
    """

    async def test_moving_both_axes_at_once_moves_both(self, mm_stage: MMStage) -> None:
        """Move both axes when both are set at once."""
        # a move whose sibling reverts it never reaches its setpoint, so the
        # wait is bounded
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
