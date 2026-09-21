from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING
from typing import Annotated as A

import numpy as np
from ophyd_async.core import (
    MovableLogic,
    SignalRW,
    StandardMovable,
    StandardReadable,
    StandardReadableFormat,
    set_and_wait_for_other_value,
)
from ophyd_async.fastcs.core import fastcs_connector
from redsun.log import Loggable

from redsun_mimir.device.containers import ReadableDeviceMap  # noqa: TC001

if TYPE_CHECKING:
    from typing import Final

    from ophyd_async.core import TimeoutCalculator

#: Where the stage's axes sit under the service's prefix.
#: ``fastcs`` names a PV path after its controller, in title case.
STAGE_GROUP = "Stage"

#: A Micro-Manager stage settles on its own grid rather than exactly where it
#: was sent: the demo XY stage lands within 0.006 um of any request, and
#: exposes no step-size property to derive this from. The service then
#: reports the position to two decimals, so a landing can read a full
#: 0.01 um from the request. `MovableLogic.move` waits for equality by
#: default, which would never be satisfied.
POSITION_TOLERANCE: Final[float] = 0.02

#: How long a move may take before it is given up as failed.
MOVE_TIMEOUT: Final[float] = 10.0


@dataclass
class MMAxisLogic(MovableLogic[float]):
    """Move logic for one axis of a Micro-Manager stage."""

    tolerance: float = POSITION_TOLERANCE

    async def calculate_timeout(
        self, old_position: float, new_position: float
    ) -> float:
        """Give every move `MOVE_TIMEOUT`, so a readback that never lands raises."""
        return MOVE_TIMEOUT

    async def move(self, new_position: float, timeout: TimeoutCalculator) -> None:
        """Write the setpoint and wait for the readback to land within tolerance."""
        await set_and_wait_for_other_value(
            self.setpoint,
            new_position,
            self.readback,
            # rtol defaults to 1e-5, which would widen the tolerance with the
            # distance travelled
            lambda value: bool(
                np.isclose(value, new_position, atol=self.tolerance, rtol=0)
            ),
            timeout=timeout(),
        )


class MMAxis(StandardReadable, StandardMovable[float]):
    """One axis of a Micro-Manager stage, moved through its service."""

    position: A[SignalRW[float], StandardReadableFormat.HINTED_SIGNAL]

    @cached_property
    def movable_logic(self) -> MovableLogic[float]:
        """Setpoint and readback of this axis, which are one signal."""
        return MMAxisLogic(setpoint=self.position, readback=self.position)


class MMStage(StandardReadable, Loggable):
    """A Micro-Manager stage, reached through the service that owns it.

    The axes the service serves are the ones the stage has: the adapter, the
    device and the axis names belong to the service's declaration.

    Parameters
    ----------
    prefix :
        PV prefix of the service, ending in ``:``. A device declared with
        ``service=`` receives it from that service.
    """

    axis: A[ReadableDeviceMap[MMAxis], StandardReadableFormat.CHILD]

    def __init__(self, prefix: str, *, name: str = "") -> None:
        super().__init__(
            name=name,
            connector=fastcs_connector(f"{prefix}{STAGE_GROUP}:", self),
        )
