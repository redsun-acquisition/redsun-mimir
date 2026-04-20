from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, TypeVar, runtime_checkable

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
    AsyncMovable,
    AsyncReadable,
    AsyncStageable,
)
from redsun.storage.protocols import HasWriterLogic

if TYPE_CHECKING:
    from ophyd_async.core import AsyncStatus, SignalR, SignalRW

T = TypeVar("T", int, float)

Array2D = np.ndarray[tuple[int, int], Any]
#: A 2D array type, with shape (height, width).

ROIType = np.ndarray[tuple[int, int, int, int], Any]
#: A region of interest (ROI) type, represented as an array of four integers: (x, y, width, height).


@runtime_checkable
class MotorProtocol(AsyncMovable[T], Protocol):
    """Protocol for individual motor axes."""

    position: SignalR[T]

    def set(self, value: float) -> AsyncStatus:
        """Move the axis to *value* absolute position.

        Returns
        -------
        AsyncStatus
            Status object of the move.
        """
        ...


@runtime_checkable
class LightProtocol(AsyncReadable, AsyncConfigurable, Protocol[T]):
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

    intensity: SignalRW[T]
    wavelength: SignalR[int]
    enabled: SignalRW[bool]

    def trigger(self) -> AsyncStatus:
        """Toggle the activation status of the light source.

        Returns
        -------
        AsyncStatus
            Status object of the operation.
        """
        ...


@runtime_checkable
class DetectorProtocol(AsyncReadable, AsyncConfigurable, AsyncStageable, Protocol):
    """Protocol for detector models.

    Attributes
    ----------
    buffer : SignalR[Array2D]
        In-memory signal holding the most recently acquired frame.
    roi : SignalRW[ROIType]
        Signal for region of interest (ROI).
    """

    buffer: SignalR[Array2D]
    roi: SignalRW[ROIType]


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
]
