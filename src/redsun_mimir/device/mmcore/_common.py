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
    """Information about a Micro-Manager serial port adapter."""

    device: str
    """Device name as recognized by the Micro-Manager Core.

    For the ``SerialManager`` adapter this is the port name itself,
    e.g. ``"COM3"``.
    """

    port: str
    """Serial port the device is connected to.

    E.g. ``"COM3"`` on Windows or ``"/dev/ttyUSB0"`` on Linux.
    """

    baudrate: int
    """Baudrate for the serial communication."""
