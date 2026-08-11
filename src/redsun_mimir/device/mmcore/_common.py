from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MMAdapterInfo:
    """Information about a Micro-Manager adapter and its devices."""

    adapter: str
    """Adapter name as recognized by the Micro-Manager Core."""

    device: str
    """Device name as recognized by the Micro-Manager Core."""

@dataclass
class MMSerialAdapterInfo(MMAdapterInfo):
    """Information about a Micro-Manager MMCoreSerialDevice adapter."""

    adapter: str
    """Adapter name as recognized by the Micro-Manager Core."""

    device: str
    """Device name as recognized by the Micro-Manager Core.
    Should be the same as port name for SerialManager, e.g. "COM3"."""

    port: str
    """Serial port to which the device is connected.
    E.g. "COM3" on Windows or "/dev/ttyUSB0" on Linux."""

    baudrate: int
    """Baudrate for the serial communication."""
