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
    """Data type of the image data, as a string (e.g. 'uint16')."""


@runtime_checkable
class MotorProtocol(AsyncReadable, Protocol):
    """Protocol for individual motor axes."""

    @property
    def axis(self) -> Mapping[str, StandardMovable[float]]:
        """Map of axis names to movable axes.

        Read-only, and a `Mapping` rather than a `DeviceMap`: a protocol's
        mutable attribute is invariant, so a device holding a map of its own
        axis class would not match, while a read-only member is covariant in
        both the mapping and the axis type.

        ``locate`` reports the commanded setpoint and the measured readback
        separately; a controller that cannot be queried reports them as equal.
        """
        ...


@runtime_checkable
class LightProtocol(AsyncConfigurable, Protocol):
    """Protocol for light source devices.

    Attributes
    ----------
    intensity :
        Settable signal for the current light intensity.
        The ``units`` field of its ``Descriptor`` carries the engineering unit.
    wavelength :
        Read-only signal for the wavelength in nanometres.
    enabled :
        Read-only signal reflecting the current on/off state.
        Updated internally each time [`trigger`][redsun_mimir.protocols.LightProtocol.trigger]
        is called.
    binary :
        Read-only signal marking the source as on/off only.
        A binary source refuses intensity changes.
    """

    @property
    def intensity(self) -> SignalRW[Any]:
        """Light source intensity.

        Read-only here, as `MotorProtocol.axis` is: a protocol's mutable
        attribute is invariant, so a device whose intensity is an ``int``
        would not match one declared ``int | float``.
        """
        ...

    @property
    def wavelength(self) -> SignalR[int]:
        """Light source wavelength."""
        ...

    @property
    def enabled(self) -> SignalRW[bool]:
        """Current on/off state of the light source."""
        ...

    @property
    def binary(self) -> SignalR[bool]:
        """Whether the source is on/off only, ignoring ``intensity``."""
        ...

    async def read(self) -> dict[str, Reading[Any]]:
        """Read the current state of the light source.

        Returns
        -------
        dict[str, Any]
            Dictionary of signal names to their current values.
        """
        ...

    async def describe(self) -> dict[str, Descriptor]:
        """Describe the light source signals.

        Returns
        -------
        dict[str, Descriptor]
            Dictionary of signal names to their descriptors.
        """
        ...

    def trigger(self) -> AsyncStatus[None]:
        """Toggle the activation status of the light source.

        Returns
        -------
        AsyncStatus[None]
            Status object of the operation.
        """
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
    """Readable signal providing access to the current data buffer.

    One frame, of shape (height, width).
    """

    exposure: SignalRW[float]
    """Signal for exposure time."""

    roi: SignalRW[np.ndarray]
    """Region of interest, as four integers: (x, y, width, height)."""

    pixel_dtype: SignalR[str]
    """Signal carrying the pixel data type."""


@runtime_checkable
class ReadableFlyer(
    DetectorProtocol,
    Preparable,
    Flyable,
    Collectable,
    WritesStreamAssets,
    Protocol,
):
    """Protocol for objects that can write to disk."""


__all__ = [
    "DetectorProtocol",
    "HasAsyncShutdown",
    "LayerSpec",
    "LightProtocol",
    "MotorProtocol",
    "ReadableFlyer",
]
