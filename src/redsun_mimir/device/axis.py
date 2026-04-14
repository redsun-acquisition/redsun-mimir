from __future__ import annotations

from typing import TYPE_CHECKING

from redsun.device import SoftAttrRW

if TYPE_CHECKING:
    from typing import Any

    from bluesky.protocols import Descriptor, Reading


class MotorAxis:
    """Lightweight child object representing one axis of a multi-axis motor.

    Not a Device subclass — instantiated directly by the parent motor device.
    The ``name`` parameter must be the fully qualified key prefix, i.e.
    ``"{device_name}-{axis_name}"`` (e.g. ``"XYStage-X"``), so that
    ``step_size`` and ``position`` produce canonical ``name-property`` keys
    that group correctly with the parent motor in the view layer.

    The ``egu`` is embedded in the descriptor ``units`` field of each
    :class:`~redsun.device.SoftAttrRW`, not exposed as a separate reading.

    Parameters
    ----------
    name :
        Fully qualified key prefix, e.g. ``"XYStage-X"``.
    egu :
        Engineering units (e.g. ``"um"``).  Stored in descriptor ``units``.
    step_size :
        Initial step size in the given engineering unit.
    """

    def __init__(self, name: str, egu: str, step_size: float) -> None:
        self._name = name
        self.step_size: SoftAttrRW[float] = SoftAttrRW(
            f"{name}-step_size", initial_value=step_size, units=egu
        )
        self.position: SoftAttrRW[float] = SoftAttrRW(
            f"{name}-position", initial_value=0.0, units=egu
        )

    @property
    def name(self) -> str:
        """The fully qualified key prefix for this axis."""
        return self._name

    def read(self) -> dict[str, Reading[Any]]:
        """Return readings for position and step_size."""
        return {**self.position.read(), **self.step_size.read()}

    def describe(self) -> dict[str, Descriptor]:
        """Return descriptors for position and step_size (includes ``units``)."""
        return {**self.position.describe(), **self.step_size.describe()}
