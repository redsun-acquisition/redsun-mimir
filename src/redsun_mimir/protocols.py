from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, TypeVar, runtime_checkable

from bluesky.protocols import (
    Collectable,
    Flyable,
    Preparable,
    Readable,
    WritesStreamAssets,
)
from ophyd_async.core import AsyncConfigurable, AsyncReadable, AsyncStageable
from redsun.storage.protocols import HasWriterLogic

if TYPE_CHECKING:
    import numpy as np
    from ophyd_async.core import AsyncStatus, SignalR, SignalRW

T = TypeVar("T", int, float)


@runtime_checkable
class MotorProtocol(Protocol):
    """Protocol for individual motor axes.

    Satisfied structurally by
    [`MotorAxis`][redsun_mimir.device.axis.MotorAxis] subclasses such as
    [`MMCoreXYAxis`][redsun_mimir.device.mmcore.MMCoreXYAxis] and
    [`MMCoreZAxis`][redsun_mimir.device.mmcore.MMCoreZAxis].
    """

    position: SignalR[float]
    step_size: SignalRW[float]

    def set(self, value: float) -> AsyncStatus:
        """Move the axis to *value* (absolute or relative, per implementation).

        Returns
        -------
        AsyncStatus
            Status object of the move.
        """
        ...


@runtime_checkable
class LightProtocol(AsyncReadable, AsyncConfigurable, Protocol[T]):
    """Protocol for light models.

    Devices satisfying this protocol expose all mutable and observable state
    as ophyd-async signals.  Static metadata (engineering unit, intensity
    range) is carried in the ``Descriptor`` documents returned by
    ``describe()`` / ``describe_configuration()``.

    Attributes
    ----------
    intensity :
        Settable signal for the current light intensity.
        The ``units`` field of its ``Descriptor`` carries the engineering unit.
    step_size :
        Settable signal for the intensity increment per UI step.
    wavelength :
        Read-only signal for the wavelength in nanometres.
    binary :
        Read-only flag; ``True`` when the source is on/off only.
    enabled :
        Read-only signal reflecting the current on/off state.
        Updated internally each time [`trigger`][redsun_mimir.protocols.LightProtocol.trigger]
        is called.
    """

    intensity: SignalRW[T]
    step_size: SignalRW[T]
    wavelength: SignalR[int]
    binary: SignalR[bool]
    enabled: SignalR[bool]

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
    buffer :
        In-memory signal holding the most recently acquired frame.
        Subscribers are notified via
        [`SignalR.subscribe`][ophyd_async.core.SignalR.subscribe] after each
        frame write.
    """

    buffer: SignalR[np.ndarray]


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
