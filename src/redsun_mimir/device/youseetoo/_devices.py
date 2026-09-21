from __future__ import annotations

from functools import cached_property
from typing import Annotated as A

from ophyd_async.core import (
    AsyncStatus,
    MovableLogic,
    SignalRW,
    StandardMovable,
    StandardReadable,
    StandardReadableFormat,
    soft_signal_r_and_setter,
    soft_signal_rw,
)
from ophyd_async.fastcs.core import fastcs_connector
from redsun.log import Loggable

from redsun_mimir.device.containers import ReadableDeviceMap  # noqa: TC001

#: Where the board's stage sits under the service's prefix.
#: ``fastcs`` names a PV path after its controller, in title case.
STAGE_GROUP = "Stage"

#: Where a board's laser sits under the service's prefix.
LASER_GROUP = "Laser1"


class UC2Axis(StandardReadable, StandardMovable[float]):
    """One axis of a YouSeeToo stage, commanded through its service.

    The board reports no position, so the readback is the value it last
    acknowledged.
    """

    position: A[SignalRW[float], StandardReadableFormat.HINTED_SIGNAL]

    @cached_property
    def movable_logic(self) -> MovableLogic[float]:
        """Setpoint and echoed readback of this axis, which are one signal."""
        return MovableLogic(setpoint=self.position, readback=self.position)


class UC2MotorDevice(StandardReadable, Loggable):
    """A YouSeeToo stage, reached through the service that owns its board.

    Parameters
    ----------
    prefix :
        PV prefix of the service, ending in ``:``; a device declared with
        ``service=`` receives it from that service.
    """

    axis: A[ReadableDeviceMap[UC2Axis], StandardReadableFormat.CHILD]

    def __init__(self, prefix: str, *, name: str = "") -> None:
        super().__init__(
            name=name,
            connector=fastcs_connector(f"{prefix}{STAGE_GROUP}:", self),
        )


class UC2LaserDevice(StandardReadable, Loggable):
    """A YouSeeToo laser, reached through the service that owns its board.

    Parameters
    ----------
    prefix :
        PV prefix of the service, ending in ``:``.
    wavelength :
        In nm; the board does not report it.
    """

    intensity: A[SignalRW[int], StandardReadableFormat.HINTED_SIGNAL]

    def __init__(self, prefix: str, *, wavelength: int = 0, name: str = "") -> None:
        self._current_intensity = 0
        super().__init__(
            name=name,
            connector=fastcs_connector(f"{prefix}{LASER_GROUP}:", self),
        )
        with self.add_children_as_readables(StandardReadableFormat.CONFIG_SIGNAL):
            self.wavelength, _ = soft_signal_r_and_setter(int, initial_value=wavelength)
            self.enabled = soft_signal_rw(bool, initial_value=False)
            # the board takes an intensity, so the light presenter may set one
            self.binary, _ = soft_signal_r_and_setter(bool, initial_value=False)

    @AsyncStatus.wrap
    async def trigger(self) -> None:
        """Turn the laser off, remembering its intensity, or back on.

        An intensity set while off has lit the laser already and is kept;
        the remembered one is restored only from zero.
        """
        enabled = await self.enabled.get_value()
        if enabled:
            self._current_intensity = await self.intensity.get_value()
            await self.intensity.set(0)
        elif await self.intensity.get_value() == 0:
            await self.intensity.set(self._current_intensity)
        await self.enabled.set(not enabled)

    async def shutdown(self) -> None:
        """Leave the laser off."""
        await self.intensity.set(0)
        await self.enabled.set(False)
