from __future__ import annotations

from ophyd_async.core import StandardReadable, StandardReadableFormat
from pymmcore_plus import CMMCorePlus as Core
from redsun.device import DeviceMap

from ._backend import mm_position_signal
from ._common import MMAdapterInfo


class MMDemoXYStage(StandardReadable):
    """Demo stage device."""

    def __init__(self, name: str, *, units: str = "um") -> None:
        super().__init__(name)
        adapter_info = MMAdapterInfo(
            adapter="DemoCamera",
            device="DXYStage",
        )
        self.core = Core.instance()
        self.core.loadDevice(self.name, adapter_info.adapter, adapter_info.device)
        self.core.initializeDevice(self.name)
        with self.add_children_as_readables(StandardReadableFormat.HINTED_SIGNAL):
            self.axis = DeviceMap(
                {
                    "x": mm_position_signal(self.core, name, "x", units),
                    "y": mm_position_signal(self.core, name, "y", units),
                }
            )


class MMDemoZStage(StandardReadable):
    """Demo stage device."""

    def __init__(self, name: str, *, units: str = "um") -> None:
        adapter_info = MMAdapterInfo(
            adapter="DemoCamera",
            device="DStage",
        )
        self.core = Core.instance()
        self.core.loadDevice(self.name, adapter_info.adapter, adapter_info.device)
        self.core.initializeDevice(self.name)
        with self.add_children_as_readables(StandardReadableFormat.HINTED_SIGNAL):
            self.axis = DeviceMap(
                {
                    "z": mm_position_signal(self.core, name, "z", units),
                }
            )
        super().__init__(name)
