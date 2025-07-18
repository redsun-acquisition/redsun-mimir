from __future__ import annotations

from typing import TYPE_CHECKING

from sunflare.model import ModelProtocol
from typing_extensions import Protocol, runtime_checkable

if TYPE_CHECKING:
    from typing import Any

    from bluesky.protocols import Descriptor, Location, Reading
    from sunflare.engine import Status

    from redsun_mimir.model import DetectorModelInfo, LightModelInfo, MotorModelInfo

__all__ = [
    "LightProtocol",
    "MotorProtocol",
    "DetectorProtocol",
]


@runtime_checkable
class Settable(Protocol):
    """Protocol for settable models.

    Reimplemented from the ``Movable`` bluesky protocol
    for a more generic use case.

    Models implementing this protocol should be able to
    set a value and return a status object.
    """

    def set(self, value: Any, **kwargs: Any) -> Status:
        """Set a value in the model.

        `set` usage is dual:

        - when no keyword arguments are provided,
          the method will set a default ``value``
          for which the model was implemented
          (i.e. motor position, temperature, etc.);
        - when keyword arguments are provided,
          the method will update a configuration value
          of the target device; for reference use ``prop``
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
    def model_info(self) -> MotorModelInfo:  # noqa: D102
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

    intensity: float | int
    enabled: bool

    def trigger(self) -> Status:
        """Toggle the activation status of the light source.

        Returns
        -------
        ``Status``
            Status object of the operation.

        """
        ...

    def read(self) -> dict[str, Reading[float | int | bool]]:
        """Read the current status of the light source.

        Returns a dictionary with the values of ``intensity`` and ``enabled``.

        Returns
        -------
        ``dict[str, Reading[int | float | bool]]``
            Dictionary with the current light intensity and activation status.

        """
        ...

    def describe(self) -> dict[str, Descriptor]:
        """Return a dictionary with the same keys as ``read``.

        The dictionary holds the metadata with relevant
        information about the light source.
        """
        ...

    @property
    def model_info(self) -> LightModelInfo:  # noqa: D102
        ...


@runtime_checkable
class DetectorProtocol(ModelProtocol, Settable, Protocol):
    """Protocol for detector models.

    Attributes
    ----------
    roi : ``tuple[int, int, int, int]``
        Region of interest (ROI) for the detector.
        The ROI is defined as a tuple of four integers:
        - (x, y, width, height), where:
            - x: X coordinate of the top-left corner of the ROI
            - y: Y coordinate of the top-left corner of the ROI
            - width: Width of the ROI
            - height: Height of the ROI
    """

    roi: tuple[int, int, int, int]

    def read(self) -> dict[str, Reading[Any]]:
        """Take a reading from the detector.

        Example return value:

        .. code-block:: python

            # requires `time` module
            return {
                "data": Reading(value=5, timestamp=time.time()),
                "other-data": Reading(value=16, timestamp=time.time()),
            }

        Returns
        -------
        ``dict[str, Reading[int | float]]``
            Dictionary with the current detector intensity.

        """
        ...

    def describe(self) -> dict[str, Descriptor]:
        """Return a dictionary with the same keys as ``read``.

        The dictionary holds the metadata with relevant
        information about the detector channels.

        The returned value can also be a ``collections.OrderedDict``.

        Example return value:

        .. code-block:: python

            return {
                "TIRF-channel": Descriptor(source="data", dtype="number", shape=[]),
                "iSCAT-channel": Descriptor(
                    source="other-data", dtype="number", shape=[]
                ),
            }
        """
        ...

    def stage(self) -> Status:
        """Prepare the detector for acquisition.

        Returns
        -------
        ``Status``
            Status object of the operation.

        """
        ...

    def unstage(self) -> Status:
        """Stop the detector acquisition.

        Returns
        -------
        ``Status``
            Status object of the operation.

        """
        ...

    def trigger(self) -> Status:
        """Trigger a reading from the detector.

        Returns
        -------
        ``Status``
            Status object of the operation.
        """
        ...

    @property
    def model_info(self) -> DetectorModelInfo:  # noqa: D102
        ...
