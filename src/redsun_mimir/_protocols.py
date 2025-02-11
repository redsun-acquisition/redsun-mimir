from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from sunflare.model import ModelProtocol

if TYPE_CHECKING:
    from bluesky.protocols import Location
    from sunflare.engine import Status


@runtime_checkable
class MotorProtocol(ModelProtocol, Protocol):
    """Protocol for motor models."""

    def set(self, value: float, **kwargs: Any) -> Status:
        """Move the motor to a given position.

        Parameters
        ----------
        value : ``float``
            New position.
        **kwargs, optional
            Additional keyword arguments.
            Accepted arguments are:
            - `axis` : ``str``, axis name.

        Returns
        -------
        ``Status``
            Status object.

        """
        ...

    def locate(self) -> Location[float]:
        """Return the current motor position.

        Returns
        -------
        ``Location[float]``
            Location object.

        """
        ...
