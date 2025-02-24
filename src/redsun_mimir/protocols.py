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

    axis: str

    def set(self, value: Any, **kwargs: Any) -> Status:
        """Set a value in the motor model.

        `set` usage is dual:

        - when no keyword arguments are provided,
          the method will set the motor position to ``value``;
        - when keyword arguments are provided,
          the method will update a configuration value
          of the target motor; for reference use ``prop``
          as the keyword name.

        Usage:

        .. code-block:: python

            # set motor position
            status = motor.set(10)

            # update configuration value
            status = motor.set("Y", prop="axis")


        Parameters
        ----------
        value : ``Any``
            New value to set.
            When no keyword arguments are provided,
            the method will set the motor position to `value`.
        **kwargs : ``Any``
            Additional keyword arguments.
            When used, the method will update
            a local configuration value.

        Attributes
        ----------
        axis : ``str``
            Motor current active axis.
            It can be changed via
            ``set(<new_axis>, prop="axis")``.

        Returns
        -------
        ``Status``
            Status object of the operation.

        """
        ...

    def locate(self) -> Location[Any]:
        """Return the current motor position.

        The returned ``Location`` is tied
        to the last active axis.

        Returns
        -------
        ``Location[Any]``
            Location object.

        """
        ...
