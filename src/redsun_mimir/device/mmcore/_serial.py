from __future__ import annotations

from ophyd_async.core import (
    StandardReadable,
    StandardReadableFormat,
    soft_signal_rw,
)
from pymmcore_plus import CMMCorePlus as Core
from redsun.log import Loggable

from ._common import MMSerialAdapterInfo

#: Milliseconds the adapter waits for a reply before giving up. Serial
#: peripherals here answer well within this; the adapter default is shorter
#: than the slowest of them.
ANSWER_TIMEOUT: float = 500.0


class MMBaseSerialDevice(StandardReadable, Loggable):
    """Micro-Manager serial port adapter.

    Loads and initialises a serial adapter in the Micro-Manager core so that
    peripherals can name it as their ``Port``. The port settings are exposed
    as configuration signals; they are written before initialisation and are
    not changed afterwards.

    Parameters
    ----------
    name : str
        MMCore device label.
    adapter : str
        MM adapter name.
    device : str
        MM device name within the adapter.
    port : str
        Serial port path, e.g. ``"COM3"`` or ``"/dev/ttyUSB0"``.
    baudrate : int
        Baud rate for the port.
    """

    def __init__(
        self,
        name: str,
        *,
        adapter: str,
        device: str,
        port: str,
        baudrate: int,
    ) -> None:
        adapter_info = MMSerialAdapterInfo(
            adapter=adapter,
            device=device,
            port=port,
            baudrate=baudrate,
        )
        self.core = Core.instance()
        self.core.loadDevice(name, adapter_info.adapter, adapter_info.device)
        # both are pre-init properties: the adapter reads them when the port
        # is opened, so setting them after initializeDevice has no effect
        self.core.setProperty(name, "BaudRate", str(adapter_info.baudrate))
        self.core.setProperty(name, "AnswerTimeout", str(ANSWER_TIMEOUT))
        self.core.initializeDevice(name)

        with self.add_children_as_readables(StandardReadableFormat.CONFIG_SIGNAL):
            self.port = soft_signal_rw(str, initial_value=adapter_info.port)
            self.baudrate = soft_signal_rw(int, initial_value=adapter_info.baudrate)
            self.answer_timeout = soft_signal_rw(
                float, initial_value=ANSWER_TIMEOUT, units="ms"
            )

        super().__init__(name=name)


class MMSerialDevice(MMBaseSerialDevice):
    """Serial port driven by Micro-Manager's ``SerialManager`` adapter.

    Parameters
    ----------
    name : str
        MMCore device label.
    port : str
        Serial port path, e.g. ``"COM3"`` or ``"/dev/ttyUSB0"``.
    baudrate : int
        Baud rate for the port.
    """

    def __init__(self, name: str, *, port: str, baudrate: int = 115200) -> None:
        # SerialManager names its devices after the port itself, so the
        # device name and the port path are necessarily the same string
        super().__init__(
            name,
            adapter="SerialManager",
            device=port,
            port=port,
            baudrate=baudrate,
        )
