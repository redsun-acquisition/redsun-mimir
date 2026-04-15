"""Abstract motor axis base class."""

from __future__ import annotations

from ophyd_async.core import (
    SignalR,
    SignalRW,
    StandardReadable,
    StandardReadableFormat,
    soft_signal_r_and_setter,
    soft_signal_rw,
)


class MotorAxis(StandardReadable):
    """Base class for a single motor axis.

    Carries ``position`` (read-only, updated by the concrete backend after
    each move) and ``step_size`` (configurable) as ophyd-async signals.

    Concrete backends (e.g.
    [`MMCoreXYAxis`][redsun_mimir.device.mmcore.MMCoreXYAxis]) add a ``set()``
    method decorated with ``@AsyncStatus.wrap`` to perform the
    hardware-specific move and call ``_set_position`` when the move completes.

    Parameters
    ----------
    name :
        Axis name; overwritten automatically when the axis is assigned to a
        parent device.
    units :
        Engineering units (e.g. ``"um"``).
    step_size :
        Initial step size in the given engineering unit.
    """

    position: SignalR[float]
    step_size: SignalRW[float]

    def __init__(
        self, name: str = "", *, units: str = "um", step_size: float = 1.0
    ) -> None:
        pos, self._set_position = soft_signal_r_and_setter(
            float, initial_value=0.0, units=units
        )
        self.position = pos
        with self.add_children_as_readables(StandardReadableFormat.CONFIG_SIGNAL):
            self.step_size = soft_signal_rw(float, initial_value=step_size, units=units)
        super().__init__(name=name)
