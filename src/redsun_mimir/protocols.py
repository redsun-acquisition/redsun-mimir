from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, TypedDict, TypeVar, runtime_checkable

import numpy as np
from bluesky.protocols import (
    Collectable,
    Flyable,
    Preparable,
    Readable,
    WritesStreamAssets,
)
from ophyd_async.core import (
    AsyncConfigurable,
    AsyncReadable,
    AsyncStageable,
)
from redsun.storage.protocols import HasWriterLogic

if TYPE_CHECKING:
    from bluesky.protocols import Descriptor, Reading
    from ophyd_async.core import AsyncStatus, SignalR, SignalRW
    from redsun.device import DeviceMap

T = TypeVar("T", int, float)

Array2D = np.ndarray[tuple[int, int], Any]
#: A 2D array type, with shape (height, width).

ROIType = np.ndarray[tuple[int, int, int, int], Any]
#: A region of interest (ROI) type, represented as an array of four integers: (x, y, width, height).


class LayerSpec(TypedDict):
    """Specification for an image layer in the view."""

    shape: tuple[int, int]
    """Shape of the image data (height, width)."""

    dtype: str
    """Data type of the image data, as a string (e.g. 'uint16')."""


@runtime_checkable
class MotorProtocol(AsyncReadable, Protocol):
    """Protocol for individual motor axes."""

    axis: DeviceMap[SignalRW[float]]
    """Map of axis names to settable signals."""


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
    """

    intensity: SignalRW[int | float]
    """Light source intensity."""
    wavelength: SignalR[int]
    """Light source wavelength."""

    enabled: SignalRW[bool]
    """Current on/off state of the light source."""

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

    def trigger(self) -> AsyncStatus:
        """Toggle the activation status of the light source.

        Returns
        -------
        AsyncStatus
            Status object of the operation.
        """
        ...


@runtime_checkable
class BufferDataProtocol(Protocol):
    """Protocol for devices that provide a continuously updated data buffer."""

    buffer: SignalR[Array2D]
    """Readable signal providing access to the current data buffer."""


@runtime_checkable
class DetectorProtocol(BufferDataProtocol, AsyncConfigurable, AsyncStageable, Protocol):
    """Protocol for detector models."""

    exposure: SignalRW[float]
    """Signal for exposure time."""

    roi: SignalRW[ROIType]
    """Signal for setting region of interest (ROI)."""

    pixel_dtype: SignalRW[str]
    """Signal for setting pixel data type."""


@runtime_checkable
class ReadableFlyer(
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
    - [`HasWriterLogic`][redsun.storage.protocols.HasWriterLogic] (``writer`` property)
    """


__all__ = [
    "DetectorProtocol",
    "LightProtocol",
    "MotorProtocol",
    "ReadableFlyer",
    "ROIType",
    "Array2D",
]
