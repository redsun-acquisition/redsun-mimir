from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, TypedDict, runtime_checkable

from bluesky.protocols import (
    Collectable,
    Flyable,
    Preparable,
    WritesStreamAssets,
)
from ophyd_async.core import (
    AsyncConfigurable,
    AsyncReadable,
    AsyncStageable,
    StandardMovable,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    import numpy as np
    from bluesky.protocols import Descriptor, Reading
    from ophyd_async.core import AsyncStatus, SignalR, SignalRW


class LayerSpec(TypedDict):
    """Specification for an image layer in the view."""

    shape: tuple[int, int]
    """Shape of the image data (height, width)."""

    dtype: str
    """Data type of the image data as a string, such as ``'uint16'``."""


@runtime_checkable
class MotorProtocol(AsyncReadable, Protocol):
    """Protocol for individual motor axes."""

    @property
    def axis(self) -> Mapping[str, StandardMovable[float]]:
        """Movable axes by name.

        Read-only and a `Mapping`, not a `DeviceMap`: a mutable protocol
        attribute is invariant, while a read-only one is covariant in both
        the mapping and the axis type, so a device holding a map of its own
        axis class matches.

        ``locate`` reports setpoint and readback separately; a controller
        that cannot be queried reports them equal.
        """
        ...


@runtime_checkable
class LightProtocol(AsyncConfigurable, Protocol):
    """Protocol for light sources.

    Attributes
    ----------
    intensity :
        Settable intensity; the ``units`` field of its ``Descriptor`` carries
        the engineering unit.
    wavelength :
        Wavelength in nanometres.
    enabled :
        On/off state, updated by each
        [`trigger`][redsun_mimir.protocols.LightProtocol.trigger] call.
    binary :
        Marks the source as on/off only; a binary source refuses intensity
        changes.
    """

    @property
    def intensity(self) -> SignalRW[Any]:
        """Light source intensity.

        Read-only, as `MotorProtocol.axis` is: a mutable protocol attribute
        is invariant, so an ``int`` intensity would not match ``int | float``.
        """
        ...

    @property
    def wavelength(self) -> SignalR[int]:
        """Wavelength in nanometres."""
        ...

    @property
    def enabled(self) -> SignalRW[bool]:
        """Current on/off state."""
        ...

    @property
    def binary(self) -> SignalR[bool]:
        """Whether the source is on/off only, ignoring ``intensity``."""
        ...

    async def read(self) -> dict[str, Reading[Any]]:
        """Return the current value of every signal, by name."""
        ...

    async def describe(self) -> dict[str, Descriptor]:
        """Return the descriptor of every signal, by name."""
        ...

    def trigger(self) -> AsyncStatus[None]:
        """Toggle the light source on or off."""
        ...


@runtime_checkable
class HasAsyncShutdown(Protocol):
    """A device releasing what it holds asynchronously."""

    async def shutdown(self) -> None:
        """Release the device's resources."""
        ...


@runtime_checkable
@runtime_checkable
class DetectorProtocol(AsyncConfigurable, AsyncStageable, Protocol):
    """Protocol for detector models."""

    buffer: SignalR[np.ndarray]
    """The latest frame, of shape (height, width)."""

    exposure: SignalRW[float]
    """Exposure time."""

    roi: SignalRW[str]
    """Region of interest, as text: ``"x,y,width,height"``, read with `Roi.parse`."""

    pixel_dtype: SignalRW[str]
    """The numpy dtype the camera reads out in; one it cannot is refused."""

    sensor_size: SignalR[np.ndarray]
    """The whole sensor as (width, height): what ``roi`` is expressed against."""


@runtime_checkable
class ReadableFlyer(
    DetectorProtocol,
    Preparable,
    Flyable,
    Collectable,
    WritesStreamAssets,
    Protocol,
):
    """Protocol for detectors that fly and write stream assets."""


__all__ = [
    "DetectorProtocol",
    "HasAsyncShutdown",
    "LayerSpec",
    "LightProtocol",
    "MotorProtocol",
    "ReadableFlyer",
]
