from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from sunflare.model import ModelProtocol

if TYPE_CHECKING:
    from bluesky.protocols import Location
    from sunflare.engine import Status


@runtime_checkable
class MotorProtocol(ModelProtocol, Protocol):
    """Protocol for motor models."""

    def set(self, value: float, /, axis: str) -> Status:
        """Move the motor to a given position along `axis`.

        Parameters
        ----------
        value : ``float``
            New position.
        axis : ``str``
            Motor axis.

        Returns
        -------
        ``Status``
            Status object.

        """
        ...

    def locate(self, /, axis: str) -> Location[float]:
        """Return the current motor position along `axis`.

        Parameters
        ----------
        axis : ``str``
            Motor axis.

        Returns
        -------
        ``Location[float]``
            Location object.

        """
        ...
