from __future__ import annotations

from abc import ABC
from collections.abc import Iterable, MutableSequence
from dataclasses import dataclass, field
from typing import Any, TypedDict, TypeVar, overload

from typing_extensions import TypeIs

T = TypeVar("T")


class GuardedList(MutableSequence[T]):
    """A list that protects against modification for read-only items.

    Parameters
    ----------
    items: Iterable[T]
        Initial items in the list.
    readonly: Iterable[T], keyword-only, optional
        Items that are read-only and cannot be modified or deleted. Default is an empty set.

    Raises
    ------
    ValueError
        If any read-only item is not present in the initial list.
    """

    def __init__(self, items: Iterable[T], /, readonly: Iterable[T] = set()) -> None:
        if any(item not in items for item in readonly):
            raise ValueError("All read-only items must be present in the initial list.")
        self._items = list(items)
        self._readonly = set(readonly)

    @property
    def readonly(self) -> frozenset[T]:
        """Frozen set of read-only items in the list."""
        return frozenset(self._readonly)

    @property
    def items(self) -> list[T]:
        """Internal list of items."""
        return self._items

    @overload
    def __getitem__(self, index: int) -> T: ...
    @overload
    def __getitem__(self, index: slice) -> GuardedList[T]: ...
    def __getitem__(self, index: int | slice) -> T | GuardedList[T]:
        if isinstance(index, slice):
            return GuardedList(self._items[index], self._readonly)
        return self._items[index]

    @overload
    def __setitem__(self, index: int, value: T) -> None: ...
    @overload
    def __setitem__(self, index: slice, value: Iterable[T]) -> None: ...
    def __setitem__(self, index: int | slice, value: T | Iterable[T]) -> None:
        if self._isslice(index):
            assert isinstance(value, Iterable), (
                "Value must be an iterable when assigning to a slice."
            )
            # check every item being overwritten
            for item in self._items[index]:
                self._check(item)
            self._items[index] = list(value)
        else:
            assert not isinstance(value, Iterable), (
                "Value must not be an iterable when assigning to a single index."
            )
            self._check(self._items[index])
            self._items[index] = value

    @overload
    def __delitem__(self, index: int) -> None: ...
    @overload
    def __delitem__(self, index: slice) -> None: ...
    def __delitem__(self, index: int | slice) -> None:
        if isinstance(index, slice):
            for item in self._items[index]:
                self._check(item)
            del self._items[index]
        else:
            self._check(self._items[index])
            del self._items[index]

    def _check(self, item: T) -> None:
        if item in self._readonly:
            raise ValueError(
                f"Item {item} is read-only and cannot be added to the list."
            )

    def __len__(self) -> int:
        return len(self._items)

    def insert(self, index: int, value: T) -> None:
        self._items.insert(index, value)

    def _isslice(self, index: int | slice) -> TypeIs[slice]:
        return isinstance(index, slice)


class CamConfigDict(TypedDict):
    adapter: str
    device: str
    properties: list[str]
    defaults: dict[str, Any]
    sensor_shape: tuple[int, int]
    starting_exposure: float
    exposure_limits: tuple[float, float]
    enum_map: dict[str, list[str]]
    numpy_dtype: dict[str, dict[str, str]]


@dataclass(frozen=True)
class BaseCamConfig(ABC):
    """Base configuration dataclass for MMCoreCameraDevice.

    Subclass to customize camera configurations.
    """

    adapter: str
    """Adapter name for the camera device."""
    device: str
    """Device name for the camera device."""
    properties: GuardedList[str]
    """List of allowed properties for the camera device."""
    defaults: dict[str, Any]
    """Default property values for the camera device."""
    sensor_shape: tuple[int, int]
    """Shape of the camera sensor (width, height)."""
    starting_exposure: float
    """Starting exposure time in milliseconds."""
    exposure_limits: tuple[float, float]
    """Exposure time limits in milliseconds (min, max)."""
    enum_map: dict[str, list[str]]
    """Mapping of property names to their allowed enum values."""
    numpy_dtype: dict[str, dict[str, str]]
    """Mapping of property names and their enum values to numpy data types."""

    def dump(self) -> CamConfigDict:
        """Dump the camera configuration to a dictionary."""
        return {
            "adapter": self.adapter,
            "device": self.device,
            "properties": self.properties.items,
            "defaults": self.defaults,
            "sensor_shape": self.sensor_shape,
            "starting_exposure": self.starting_exposure,
            "exposure_limits": self.exposure_limits,
            "enum_map": self.enum_map,
            "numpy_dtype": self.numpy_dtype,
        }


@dataclass(frozen=True)
class DemoCamConfig(BaseCamConfig):
    """Configuration dataclass for MMCoreCameraDevice.

    Subclass to customize camera configurations.
    """

    adapter: str = "DemoCamera"
    device: str = "DCam"
    properties: GuardedList[str] = field(
        default_factory=lambda: GuardedList(
            [
                "PixelType",
                "Mode",
                "BeadBlurRate",
                "BeadBrightness",
                "BeadDensity",
                "BeadSize",
            ],
            readonly=["Mode"],
        )
    )
    defaults: dict[str, Any] = field(
        default_factory=lambda: {
            "PixelType": "16bit",
            "Mode": "Fluorescent Beads",
            "BeadBlurRate": 0.5,
            "BeadBrightness": 1,
            "BeadDensity": 150,
            "BeadSize": 5,
        }
    )
    sensor_shape: tuple[int, int] = (512, 512)
    starting_exposure: float = 50.0
    exposure_limits: tuple[float, float] = (0.0, 10000.0)
    enum_map: dict[str, list[str]] = field(
        default_factory=lambda: {
            "PixelType": ["8bit", "16bit", "32bit"],
            "Mode": [
                "Artificial Waves",
                "Color Test Pattern",
                "Fluorescent Beads",
                "Noise",
            ],
        }
    )
    numpy_dtype: dict[str, dict[str, str]] = field(
        default_factory=lambda: {
            "PixelType": {
                "8bit": "uint8",
                "16bit": "uint16",
                "32bit": "float32",
            }
        }
    )


@dataclass(frozen=True)
class DahengCamConfig(BaseCamConfig):
    """Configuration dataclass for Daheng cameras.

    Default camera for mimir microscope.
    """

    adapter: str = "DahengGalaxy"
    device: str = "DahengCamera"
    properties: GuardedList[str] = field(
        default_factory=lambda: GuardedList(["PixelType", "Gain"])
    )
    defaults: dict[str, Any] = field(
        default_factory=lambda: {"PixelType": "Mono8", "Gain": 0.0}
    )
    sensor_shape: tuple[int, int] = (1200, 1920)
    starting_exposure: float = 50.0
    exposure_limits: tuple[float, float] = (0.0, 10000.0)
    enum_map: dict[str, list[str]] = field(
        default_factory=lambda: {
            "PixelType": ["Mono8", "Mono10"],
        }
    )
    numpy_dtype: dict[str, dict[str, str]] = field(
        default_factory=lambda: {
            "PixelType": {
                "Mono8": "uint8",
                "Mono10": "uint16",
            }
        }
    )
