from __future__ import annotations

from typing import TYPE_CHECKING

from ophyd_async.core import (
    StandardReadable,
    StandardReadableFormat,
    soft_signal_rw,
)
from pymmcore_plus import CMMCorePlus as Core
from redsun.log import Loggable

from ._backend import mm_property_signal
from ._common import MMAdapterInfo

if TYPE_CHECKING:
    from collections.abc import Mapping


class MMBaseStatedDevice(StandardReadable, Loggable):
    """Micro-Manager device selecting one of a finite set of positions.

    The ``state`` signal speaks labels, not indices: *labels* maps the name a
    user recognises to the position the adapter switches to, and the signal
    publishes those names as its choices, so a consumer builds its selector
    from the DataKey alone.

    Parameters
    ----------
    name : str
        MMCore device label.
    adapter_info : MMAdapterInfo
        Adapter and device identifiers.
    labels : Mapping[str, int]
        Label of each position, keyed by the name to expose for it.
    pre_init_props : Mapping[str, str] | None
        Properties to write before ``initializeDevice``.
    """

    def __init__(
        self,
        name: str,
        *,
        adapter_info: MMAdapterInfo,
        labels: Mapping[str, int],
        pre_init_props: Mapping[str, str] | None = None,
    ) -> None:
        if not labels:
            raise ValueError(f"{name!r}: at least one position label is required")

        self.core = Core.instance()
        self.core.loadDevice(name, adapter_info.adapter, adapter_info.device)
        for prop, value in (pre_init_props or {}).items():
            self.core.setProperty(name, prop, value)
        self.core.initializeDevice(name)

        with self.add_children_as_readables(StandardReadableFormat.CONFIG_SIGNAL):
            # the adapter spells a position as the decimal index it holds in
            # its "State" property, so the enum map is label -> str(index)
            self.state = mm_property_signal(
                self.core,
                name,
                "State",
                enum_map={label: str(position) for label, position in labels.items()},
            )

        super().__init__(name)


class MMASIFWController(StandardReadable, Loggable):
    """ASI filter wheel controller.

    The controller owns the serial link; a
    [`MMASIFilterWheel`][redsun_mimir.device.mmcore.MMASIFilterWheel] attaches
    to it as a peripheral and must be built after it.

    Parameters
    ----------
    name : str
        MMCore device label.
    port : str
        MMCore label of the serial port device to communicate over.
    """

    def __init__(self, name: str, *, port: str = "COM3") -> None:
        adapter_info = MMAdapterInfo(adapter="ASIFW1000", device="ASIFWController")
        self.core = Core.instance()
        self.core.loadDevice(name, adapter_info.adapter, adapter_info.device)
        self.core.setProperty(name, "Port", port)
        self.core.initializeDevice(name)

        with self.add_children_as_readables(StandardReadableFormat.CONFIG_SIGNAL):
            self.port = soft_signal_rw(str, initial_value=port)

        super().__init__(name)


class MMASIFilterWheel(MMBaseStatedDevice):
    """ASI filter wheel.

    Parameters
    ----------
    name : str
        MMCore device label.
    labels : Mapping[str, int]
        Filter mounted at each position, keyed by the name to expose for it.
    wheel_number : int
        Index of the wheel on the controller.
    """

    def __init__(
        self,
        name: str,
        *,
        labels: Mapping[str, int],
        wheel_number: int = 0,
    ) -> None:
        adapter_info = MMAdapterInfo(adapter="ASIFW1000", device="ASIFilterWheel")
        super().__init__(
            name,
            adapter_info=adapter_info,
            labels=labels,
            pre_init_props={"ASIFilterWheelNumber": str(wheel_number)},
        )
