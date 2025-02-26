from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from sunflare.model import ModelProtocol
from typing_extensions import Protocol, runtime_checkable

if TYPE_CHECKING:
    from typing import Any, Union

    from bluesky.protocols import Location, Reading
    from event_model.documents.event_descriptor import DataKey
    from sunflare.engine import Status

    from redsun_mimir.model import LightModelInfo, StageModelInfo


@runtime_checkable
class Settable(Protocol):
    """Protocol for settable models.

    Reimplemented from the ``Movable`` bluesky protocol
    for a more generic use case.

    Models implementing this protocol should be able to
    set a value and return a status object.
    """

    @abstractmethod
    def set(self, value: Any, **kwargs: Any) -> Status:
        """Set a value in the model.

        `set` usage is dual:

        - when no keyword arguments are provided,
          the method will set a default ``value``
          for which the model was implemented
          (i.e. motor position, temperature, etc.);
        - when keyword arguments are provided,
          the method will update a configuration value
          of the target motor; for reference use ``prop``
          as the keyword name.

        For example, a motorized device can use
        this protocol as follows:

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
            the method will set the object to ``value``.
        **kwargs : ``Any``
            Additional keyword arguments.
            When used, the method will update
            a local configuration value.

        Returns
        -------
        ``Status``
            Status object of the operation.

        """
        ...


@runtime_checkable
class MotorProtocol(ModelProtocol, Settable, Protocol):
    """Protocol for motor models.

    Implements the ``Locatable`` protocol.

    Attributes
    ----------
    axis : ``str``
        Motor current active axis.
        It can be changed via
        ``set(<new_axis>, prop="axis")``.

    """

    axis: str

    @abstractmethod
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

    @property
    @abstractmethod
    def model_info(self) -> StageModelInfo:  # noqa: D102
        ...


@runtime_checkable
class LightProtocol(ModelProtocol, Settable, Protocol):
    """Protocol for light models.

    Implements the ``Readable`` protocol.

    Attributes
    ----------
    intensity : ``float | int``
        Light intensity.
    enabled : ``bool``
        Light activation status.
        - ``True``: light is on
        - ``False``: light is off

    """

    intensity: Union[float, int]
    enabled: bool

    @abstractmethod
    def trigger(self) -> Status:
        """Toggle the activation status of the light source.

        Returns
        -------
        ``Status``
            Status object of the operation.

        """
        ...

    @abstractmethod
    def read(self) -> dict[str, Reading[Union[float, int]]]:
        """Read current light intensity.

        Example return value:

        .. code-block:: python

            # requires `time` module
            return {
                "TIRF-channel": Reading(value=5, timestamp=time.time()),
                "iSCAT-channel": Reading(value=16, timestamp=time.time()),
            }

        Returns
        -------
        ``dict[str, Reading[int | float]]``
            Dictionary with the current light intensity.

        """
        ...

    @abstractmethod
    def describe(self) -> dict[str, DataKey]:
        """Return a dictionary with the same keys as ``read``.

        The dictionary holds the metadata with relevant
        information about the light channels.

        The returned can also be a ``collections.OrderedDict``

        Example return value:

        .. code-block:: python

            return {
                "TIRF-channel": DataKey(
                    source="MyLaserClass", dtype="number", shape=[]
                ),
                "iSCAT-channel": DataKey(
                    source="MyLaserClass", dtype="number", shape=[]
                ),
            }
        """
        ...

    @property
    @abstractmethod
    def model_info(self) -> LightModelInfo:  # noqa: D102
        ...
