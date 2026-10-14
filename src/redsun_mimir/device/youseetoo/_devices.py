from __future__ import annotations

from functools import cached_property
from typing import Annotated as A

from ophyd_async.core import (
    MovableLogic,
    SignalRW,
    StandardMovable,
    StandardReadable,
    StandardReadableFormat,
    derived_signal_rw,
    soft_signal_r_and_setter,
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

    The readback is where the service found the board's stepper at startup,
    and the value it last acknowledged after that.
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


def is_lit(intensity: int) -> bool:
    """Tell whether a laser at *intensity* is on."""
    return intensity > 0


class UC2LaserDevice(StandardReadable, Loggable):
    """A YouSeeToo laser, reached through the service that owns its board.

    The board knows only an intensity, so `enabled` is derived from it: the
    laser is on while its intensity is above 0. Switching it off remembers
    the intensity and writes 0; switching it on writes the remembered one
    back. An intensity set while the laser is off lights it.

    Parameters
    ----------
    prefix :
        PV prefix of the service, ending in ``:``.
    wavelength :
        In nm; the board does not report it.
    """

    intensity: A[SignalRW[int], StandardReadableFormat.HINTED_SIGNAL]

    def __init__(self, prefix: str, *, wavelength: int = 0, name: str = "") -> None:
        self._saved_intensity = 0
        super().__init__(
            name=name,
            connector=fastcs_connector(f"{prefix}{LASER_GROUP}:", self),
        )
        with self.add_children_as_readables(StandardReadableFormat.CONFIG_SIGNAL):
            self.wavelength, _ = soft_signal_r_and_setter(int, initial_value=wavelength)
            self.enabled = derived_signal_rw(
                is_lit,
                self._switch,
                derived_datatype=bool,
                intensity=self.intensity,
            )

    async def _switch(self, on: bool) -> None:
        current = await self.intensity.get_value()
        if not on:
            if current > 0:
                self._saved_intensity = current
            await self.intensity.set(0)
        elif current == 0:
            if self._saved_intensity == 0:
                self.logger.info(
                    f"{self.name} has no intensity to restore; it stays off"
                )
            await self.intensity.set(self._saved_intensity)

    async def shutdown(self) -> None:
        """Leave the laser off."""
        await self.intensity.set(0)
