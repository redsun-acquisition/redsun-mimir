from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from typing import Any, TypedDict


class SerialConfigDict(TypedDict):
    adapter: str
    device: str
    port: str
    baudrate: int


@dataclass(frozen=True)
class BaseSerialConfig(ABC):
    """Base configuration dataclass for MMCoreSerialDevice."""

    adapter: str = "SerialManager"
    """Adapter name for the serial device."""

    device: str = "COM3"
    """Device name for the serial device (usually the COM port name)."""

    port: str = "COM3"
    """COM port to connect to."""

    baudrate: int = 115200
    """Baud rate for serial communication."""

    def dump(self) -> SerialConfigDict:
        """Dump the serial configuration to a dictionary."""
        return {
            "adapter": self.adapter,
            "device": self.device,
            "port": self.port,
            "baudrate": self.baudrate,
        }


@dataclass(frozen=True)
class SerialConfig(BaseSerialConfig):
    """Default configuration for a serial device."""

    port: str = "COM3"
    baudrate: int = 115200
