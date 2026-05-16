from __future__ import annotations

import time
from typing import TYPE_CHECKING

from pymmcore_plus import CMMCorePlus as Core
from redsun.device import Device
from redsun.log import Loggable

from redsun_mimir.device.mmcore.configs import (
    BaseSerialConfig,
    SerialConfig,
)

if TYPE_CHECKING:
    from typing import Any, Literal
    from redsun.storage import PrepareInfo
    from redsun.engine import Status


class MMCoreSerialDevice(Device, Loggable):
    """Device control for a Micro-Manager serial port.

    Parameters
    ----------
    name : str
        Identity key of the device.
    config : Literal["default"], optional
        Predefined configuration for the serial device.
    """

    def __init__(
        self,
        name: str,
        /,
        config: Literal["serial", "default"] | None = None,
        **kwargs: Any,
    ) -> None:
        self.config: BaseSerialConfig
        match config:
            case "serial" | "default":
                self.config = SerialConfig()
            case _:
                if config is None:
                    self.config = SerialConfig()
                else:
                    raise ValueError(f"Unknown serial config: {config}")

        # Update config with kwargs if provided (e.g. from YAML)
        conf_dict = self.config.dump()
        conf_dict.update(kwargs)

        super().__init__(name, **conf_dict)
        self._core = Core.instance()
        try:
            self._core.loadDevice(self.name, conf_dict["adapter"], conf_dict["device"])
            # For SerialManager, BaudRate is a pre-init property
            self._core.setProperty(self.name, "BaudRate", str(conf_dict["baudrate"]))
            self._core.initializeDevice(self.name)
        except Exception as e:
            raise RuntimeError(f"Failed to initialize MMCore serial device: {e}") from e

    def shutdown(self) -> None:
        """Shutdown the serial device."""
        try:
            self._core.unloadDevice(self.name)
        except Exception as e:
            self.logger.warning(f"Failed to unload serial device {self.name}: {e}")

    # The following methods are required by the Device/Protocol but serial ports
    # usually don't provide readings in this context.
    def read_configuration(self) -> dict[str, Any]:
        return {}

    def describe_configuration(self) -> dict[str, Any]:
        return {}

    def prepare(self, _: PrepareInfo) -> Status:
        from redsun.engine import Status
        s = Status()
        s.set_finished()
        return s
