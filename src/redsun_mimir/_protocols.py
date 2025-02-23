from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from sunflare.model import ModelProtocol

if TYPE_CHECKING:
    from bluesky.protocols import Location
    from sunflare.engine import Status


@runtime_checkable
class MotorProtocol(ModelProtocol, Protocol):
    """Protocol for motor models."""

    def set(self, value: float) -> Status:
        """Move the motor to a given position along `axis`.

        Parameters
        ----------
        value : ``float``
            New position.
        axis : ``str``, keyword argument
            Motor axis.

        Returns
        -------
        ``Status``
            Status object.

        """
        ...

    def locate(self) -> Location:
        """Return the current motor position along `axis`.

        Parameters
        ----------
        axis : ``str``, keyword argument
            Motor axis.

        Returns
        -------
        ``Location``
            Location object.

        """
        ...
