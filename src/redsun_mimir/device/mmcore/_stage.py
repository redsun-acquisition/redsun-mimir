from __future__ import annotations

from ophyd_async.core import DeviceMap, StandardMovable, StandardReadable
from pymmcore_plus import CMMCorePlus as Core
from redsun.log import Loggable

from ._backend import MMAxis
from ._common import MMAdapterInfo


class MMDemoXYStage(StandardReadable, Loggable):
    """Demo stage device."""

    axis: DeviceMap[StandardMovable[float]]

    def __init__(self, name: str, *, units: str = "um") -> None:
        adapter_info = MMAdapterInfo(
            adapter="DemoCamera",
            device="DXYStage",
        )
        self.core = Core.instance()
        self.core.loadDevice(name, adapter_info.adapter, adapter_info.device)
        self.core.initializeDevice(name)
        # the signals live *only* in the map: assigning them to the device
        # first would parent them here, and a Device cannot be re-parented
        # into the DeviceMap afterwards. Readables are taken from the map's
        # values so readings are keyed "<device>-axis-<name>", which is what
        # redsun's parse_map_key(key, "axis") splits.
        self.axis = DeviceMap(
            {
                "x": MMAxis(self.core, name, "x", units),
                "y": MMAxis(self.core, name, "y", units),
            }
        )
        self.add_readables(list(self.axis.values()))
        super().__init__(name)


class MMDemoZStage(StandardReadable):
    """Demo stage device."""

    axis: DeviceMap[StandardMovable[float]]

    def __init__(self, name: str, *, units: str = "um") -> None:
        adapter_info = MMAdapterInfo(
            adapter="DemoCamera",
            device="DStage",
        )
        self.core = Core.instance()
        self.core.loadDevice(name, adapter_info.adapter, adapter_info.device)
        self.core.initializeDevice(name)
        # see MMDemoXYStage for why the signals live only in the map
        self.axis = DeviceMap({"z": MMAxis(self.core, name, "z", units)})
        self.add_readables(list(self.axis.values()))
        super().__init__(name)
