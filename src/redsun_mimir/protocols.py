from __future__ import annotations

from typing import TYPE_CHECKING

from sunflare.model import ModelProtocol
from typing_extensions import Protocol, runtime_checkable

if TYPE_CHECKING:
    from typing import Any

    from bluesky.protocols import Location
    from sunflare.engine import Status


@runtime_checkable
class MotorProtocol(ModelProtocol, Protocol):
    """Protocol for motor models."""

    def set(self, value: float) -> Status:
        """Move the motor to a given position.

        Axis is specified via the `configure`
        method, i.e.

        .. code-block:: python

            motor.configure(axis="x")
            motor.set(100)

        Parameters
        ----------
        value : ``float``
            New position.

        Returns
        -------
        ``Status``
            Status object.

        """
        ...

    def locate(self) -> Location[Any]:
        """Return the current motor position along `axis`.

        Returns
        -------
        ``Location[Any]``
            Location object.

        """
        ...
