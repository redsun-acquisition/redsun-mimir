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
    from ophyd_async.core import SignalR, SignalRW
    from redsun.engine import Deferrals
    from redsun.engine.actions import ActionManager


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
class DetectorProtocol(AsyncConfigurable, AsyncStageable, Protocol):
    """Protocol for detector models."""

    buffer: SignalR[np.ndarray]
    """The latest frame, of shape (height, width)."""

    exposure: SignalRW[float]
    """Exposure time."""

    roi: SignalRW[str]
    """Region of interest, as text: ``"x,y,width,height"``, read with `Roi.parse`."""

    pixel_dtype: SignalRW[str]
    """The numpy dtype the camera reads out in, one of the choices it describes."""

    sensor_size: SignalR[np.ndarray]
    """The whole sensor as (width, height): what ``roi`` is expressed against."""


@runtime_checkable
class HasBuffer(Protocol):
    """A device publishing its latest frame."""

    @property
    def buffer(self) -> SignalR[np.ndarray]:
        """The latest frame, of shape (height, width)."""
        ...


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


@runtime_checkable
class DescribesDetectors(Protocol):
    """A component describing the detectors of the session."""

    def detector_descriptors(self) -> dict[str, Descriptor]:
        """Return the configuration descriptors of every detector, by data key."""
        ...

    def detector_readings(self) -> dict[str, Reading[Any]]:
        """Return the current configuration readings of every detector, by data key."""
        ...

    def detector_layer_specs(self) -> dict[str, LayerSpec]:
        """Return the shape and dtype of the layer each detector feeds, by name."""
        ...


@runtime_checkable
class HoldsDeferrals(Protocol):
    """A component running plans, whose engine applies deferred changes."""

    def plan_deferrals(self) -> Deferrals:
        """Return the deferrals of the engine running the plans."""
        ...


@runtime_checkable
class HasActions(Protocol):
    """A component whose plans wait on the actions it holds."""

    @property
    def actions(self) -> ActionManager:
        """The actions the component's running plan offers."""
        ...


__all__ = [
    "DescribesDetectors",
    "DetectorProtocol",
    "HasActions",
    "HasBuffer",
    "HoldsDeferrals",
    "LayerSpec",
    "MotorProtocol",
    "ReadableFlyer",
]
