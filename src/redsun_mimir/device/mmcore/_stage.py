from __future__ import annotations

from typing import TYPE_CHECKING

from ophyd_async.core import DeviceMap, StandardReadable
from pymmcore_plus import CMMCorePlus as Core
from redsun.log import Loggable

from ._backend import mm_position_signal
from ._common import MMAdapterInfo

if TYPE_CHECKING:
    from ophyd_async.core import SignalRW


class MMDemoXYStage(StandardReadable, Loggable):
    """Demo stage device."""

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
                "x": mm_position_signal(self.core, name, "x", units),
                "y": mm_position_signal(self.core, name, "y", units),
            }
        )
        self.add_readables(list(self.axis.values()))
        super().__init__(name)


class MMDemoZStage(StandardReadable):
    """Demo stage device."""

    axis: DeviceMap[SignalRW[float]]

    def __init__(self, name: str, *, units: str = "um") -> None:
        adapter_info = MMAdapterInfo(
            adapter="DemoCamera",
            device="DStage",
        )
        self.core = Core.instance()
        self.core.loadDevice(name, adapter_info.adapter, adapter_info.device)
        self.core.initializeDevice(name)
        # see MMDemoXYStage for why the signals live only in the map
        self.axis = DeviceMap({"z": mm_position_signal(self.core, name, "z", units)})
        self.add_readables(list(self.axis.values()))
        super().__init__(name)
