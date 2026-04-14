from __future__ import annotations

import abc
from typing import TYPE_CHECKING

from bluesky.protocols import Locatable
from redsun.device import Device, SoftAttrRW

if TYPE_CHECKING:
    from typing import Any

    from bluesky.protocols import Descriptor, Location, Reading


class MotorAxis(Device, Locatable[float], abc.ABC):
    """Abstract base for a single motor axis.

    Carries ``step_size`` and ``position`` as
    [`SoftAttrRW`][redsun.device.SoftAttrRW] signals whose names are
    injected automatically when the axis is assigned to a parent
    [`Device`][redsun.device.Device] attribute.

    Concrete backends (e.g.
    [`MMCoreXYAxis`][redsun_mimir.device.mmcore.MMCoreXYAxis]) override
    [`set`][] to perform the hardware-specific move.

    Parameters
    ----------
    name :
        Initial name; overwritten automatically when the axis is assigned
        to a parent device attribute via
        [`set_name`][redsun.device.Device.set_name].
    egu :
        Engineering units (e.g. ``"um"``). Stored in descriptor ``units``.
    step_size :
        Initial step size in the given engineering unit.
    """

    def __init__(self, name: str, egu: str, step_size: float) -> None:
        super().__init__(name)
        self.step_size: SoftAttrRW[float] = SoftAttrRW[float](step_size, units=egu)
        self.position: SoftAttrRW[float] = SoftAttrRW[float](0.0, units=egu)

    def locate(self) -> Location[float]:
        """Return the current setpoint and readback position.

        Returns
        -------
        Location[float]
            Both ``setpoint`` and ``readback`` reflect the last value set
            via [`set`][].
        """
        pos = self.position.get_value()
        return {"setpoint": pos, "readback": pos}

    def read(self) -> dict[str, Reading[Any]]:
        """Return readings for ``position`` and ``step_size``."""
        return {**self.position.read(), **self.step_size.read()}

    def describe(self) -> dict[str, Descriptor]:
        """Return descriptors for ``position`` and ``step_size``."""
        return {**self.position.describe(), **self.step_size.describe()}
