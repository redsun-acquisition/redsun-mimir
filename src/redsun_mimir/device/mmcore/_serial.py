from __future__ import annotations

from typing import TYPE_CHECKING

from ophyd_async.core import (
    StandardReadable,
    StandardReadableFormat,
    soft_signal_rw,
)
from pymmcore_plus import CMMCorePlus as Core
from redsun.log import Loggable

from ._backend import (
    mm_property_signal,
)

from ._common import MMSerialAdapterInfo

if TYPE_CHECKING:
    from ophyd_async.core import SignalRW


class MMBaseSerialDevice(StandardReadable, Loggable):
    """Micro-Manager serial device adapter wrapper.

    This device loads and initializes a serial adapter in the MM Core and
    exposes basic configuration signals (port, baudrate) under the
    configuration signal group.

    Parameters
    ----------
    name:
        Instance name / label to register with the MM Core.
    adapter:
        MM adapter name (defaults to "SerialManager").
    device:
        MM device name for the adapter (defaults to the adapter name).
    port:
        Serial port path (e.g. "COM3" or "/dev/ttyUSB0").
    baudrate:
        Baud rate for the port.
    """

    def __init__(
        self,
        name: str,
        adapter: str,
        device: str,
        port: str,
        baudrate: int,
    ) -> None:
        self.core = Core.instance()
        adapter_info = MMSerialAdapterInfo(
            adapter=adapter,
            device=device,
            port=port,
            baudrate=baudrate
        )
        # Load and initialize the device in the Micro-Manager core
        self.core.loadDevice(name, adapter_info.adapter, adapter_info.device)
        try:
            self.core.setProperty(name, "BaudRate", adapter_info.baudrate)
            self.core.setProperty(name, "AnswerTimeout", 500.0000)
        except Exception:
            pass

        self.core.initializeDevice(name)
        # expose configuration signals
        with self.add_children_as_readables(StandardReadableFormat.CONFIG_SIGNAL):
            self.baudrate: SignalRW[int] = mm_property_signal(
                self.core, name, "BaudRate", readonly=True, datatype=int
            )
            self.answer_timeout: SignalRW[int] = mm_property_signal(
                self.core, name, "AnswerTimeout", readonly=True, datatype=float
            )

        super().__init__(name=name)


class MMSerialDevice(MMBaseSerialDevice):
    """Alias for MMBaseSerialDevice for easier configuration-based instantiation.

    Parameters
    ----------
    name : str
        MMCore device label.
    port : str
        COM port path (e.g. ``"COM3"``).
    baudrate : int
        Baud rate (default 115200).
    device : str
        MMCore device name for the adapter (default ``"COM3"``).
        Should match the ``port`` argument.
    """

    def __init__(self, name: str, **kwargs) -> None:
        device = kwargs.pop("device", "COM3")
        super().__init__(
            name,
            adapter="SerialManager",
            device=device,
            **kwargs,
        )