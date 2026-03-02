from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from typing import Any, TypedDict


class CamConfigDict(TypedDict):
    adapter: str
    device: str
    allowed_properties: list[str]
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
    allowed_properties: list[str]
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
            "allowed_properties": self.allowed_properties,
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
    """Adapter name for the camera device."""
    device: str = "DCam"
    """Device name for the camera device."""
    allowed_properties: list[str] = field(default_factory=lambda: ["PixelType"])
    """List of allowed properties for the camera device."""
    defaults: dict[str, Any] = field(default_factory=lambda: {"PixelType": "16bit"})
    """Default property values for the camera device."""
    sensor_shape: tuple[int, int] = (512, 512)
    """Shape of the camera sensor (width, height)."""
    starting_exposure: float = 50.0
    """Starting exposure time in milliseconds."""
    exposure_limits: tuple[float, float] = (0.0, 10000.0)
    """Exposure time limits in milliseconds (min, max)."""
    enum_map: dict[str, list[str]] = field(
        default_factory=lambda: {
            "PixelType": ["8bit", "16bit", "32bit"],
        }
    )
    """Mapping of property names to their allowed enum values."""
    numpy_dtype: dict[str, dict[str, str]] = field(
        default_factory=lambda: {
            "PixelType": {
                "8bit": "uint8",
                "16bit": "uint16",
                "32bit": "float32",
            }
        }
    )
    """Mapping of property names and their enum values to numpy data types."""


@dataclass(frozen=True)
class DahengCamConfig(BaseCamConfig):
    """Configuration dataclass for Daheng cameras.

    Default camera for mimir microscope.
    """

    adapter: str = "DahengGalaxy"
    device: str = "DahengCamera"
    allowed_properties: list[str] = field(default_factory=lambda: ["PixelType", "Gain"])
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
