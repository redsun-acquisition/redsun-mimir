from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from bluesky.protocols import (
    Collectable,
    Flyable,
    Locatable,
    Movable,
    Preparable,
    Readable,
    Stageable,
    Triggerable,
    WritesStreamAssets,
)
from redsun.device import AttrR, PDevice
from redsun.storage import HasWriterLogic

if TYPE_CHECKING:
    import numpy.typing as npt
    from bluesky.protocols import Descriptor, Reading
    from redsun.engine import Status


@runtime_checkable
class Settable(Movable[Any], Protocol):
    """Protocol for settable devices.

    Extends [`Movable`][bluesky.protocols.Movable] with support for
    keyword-argument property updates alongside the standard positional
    ``value`` argument.

    Parameters
    ----------
    value :
        New value. When no keyword arguments are provided the device is
        moved to this value (position, intensity, etc.).
    **kwargs :
        Optional property selector.  Pass ``prop="<name>"`` or
        ``propr="<name>"`` to update a named configuration property
        instead of performing a move.

    Examples
    --------
    ```python
    # Move motor
    status = motor.set(10.0)
    # Switch active axis
    status = motor.set("Y", prop="axis")
    ```
    """

    def set(self, value: Any, **kwargs: Any) -> Status:
        """Set a value or update a configuration property."""
        ...


@runtime_checkable
class MotorProtocol(PDevice, Locatable[Any], Protocol):
    """Protocol for individual motor axes.

    Extends [`PDevice`][redsun.device.PDevice] with
    [`Locatable`][bluesky.protocols.Locatable], which already includes
    [`Movable`][bluesky.protocols.Movable] (and therefore ``set()`` and
    ``locate()``).

    Satisfied structurally by
    [`MotorAxis`][redsun_mimir.device.axis.MotorAxis] subclasses such as
    [`MMCoreXYAxis`][redsun_mimir.device.mmcore.MMCoreXYAxis] and
    [`MMCoreZAxis`][redsun_mimir.device.mmcore.MMCoreZAxis].
    """


@runtime_checkable
class LightProtocol(PDevice, Settable, Readable[Any], Triggerable, Protocol):
    """Protocol for light models.

    Attributes
    ----------
    intensity :
        Light intensity.
    enabled :
        Light activation status (``True`` = on, ``False`` = off).
    binary :
        Whether the light source is binary (on/off only).
    wavelength :
        Wavelength of the light source in nanometres.
    egu :
        Engineering unit for intensity (e.g. ``"mW"``).
    intensity_range :
        Minimum and maximum intensity values.
    step_size :
        Intensity increment per step.
    """

    intensity: Any
    enabled: Any
    binary: bool
    wavelength: int
    egu: str
    intensity_range: tuple[int | float, ...]
    step_size: int | float

    def trigger(self) -> Status:
        """Toggle the activation status of the light source.

        Returns
        -------
        Status
            Status object of the operation.
        """
        ...

    def read(self) -> dict[str, Reading[float | int | bool]]:
        """Read the current status of the light source.

        Returns a dictionary with the values of ``intensity`` and ``enabled``.

        Returns
        -------
        dict[str, Reading[int | float | bool]]
            Dictionary with the current light intensity and activation status.
        """
        ...

    def describe(self) -> dict[str, Descriptor]:
        """Return a dictionary with the same keys as ``read``.

        The dictionary holds metadata with relevant information about the
        light source.
        """
        ...


@runtime_checkable
class DetectorProtocol(PDevice, Settable, Readable[Any], Stageable, Protocol):
    """Protocol for detector models.

    Attributes
    ----------
    roi :
        Region of interest as ``(x, y, width, height)``.
    sensor_shape :
        Sensor dimensions as ``(height, width)``.
    buffer :
        In-memory circular buffer holding the most recently acquired frame.
        Subscribers are notified via [`AttrR.subscribe`][] after each frame write.
    """

    roi: tuple[int, int, int, int]
    sensor_shape: tuple[int, int]
    buffer: AttrR[npt.NDArray[Any]]


@runtime_checkable
class ReadableFlyer(
    PDevice,
    Readable[Any],
    Preparable,
    Flyable,
    Collectable,
    WritesStreamAssets,
    HasWriterLogic,
    Protocol,
):
    """Protocol for objects that are both Readable and Flyable.

    A model compliant with this protocol can read data continuously
    while flying and provides methods to retrieve the file paths where
    data is stored.

    Required protocols:

    - [`Readable`][bluesky.protocols.Readable] (``read()`` and ``describe()``)
    - [`Flyable`][bluesky.protocols.Flyable] (``kickoff()`` and ``complete()``)
    - [`Preparable`][bluesky.protocols.Preparable] (``prepare()``)
    - [`Collectable`][bluesky.protocols.Collectable] (``describe_collect()``)
    - [`WritesStreamAssets`][bluesky.protocols.WritesStreamAssets] (``collect_asset_docs()``)
    - [`HasWriterLogic`][redsun.storage.HasWriterLogic] (``writer_logic`` property)
    """

    sensor_shape: tuple[int, int]
