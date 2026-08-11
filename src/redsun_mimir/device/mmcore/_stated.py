"""Stated devices (ASI filter wheel controller + filter wheel)."""

from __future__ import annotations

from ophyd_async.core import StandardReadable, StandardReadableFormat, soft_signal_rw
from pymmcore_plus import CMMCorePlus as Core
from redsun.log import Loggable

from ._backend import mm_property_signal
from ._common import MMAdapterInfo

_FW_LABELS: dict[int, str] = {
    0: "610BP60",
    1: "555BP30",
    2: "676BP34",
    3: "open",
    4: "closed",
    5: "470BP24",
    6: "518BP",
    7: "632BP60",
}

_FW_COLOR_FILTER_MAP: dict[str, int] = {
    "off": 4,
    "brightfield": 3,
    "514_teal": 1,
    "640_red": 2,
    "470_cyan": 6,
    "561_green": 7,
    "445_blue": 0,
    "395_violet": 5,
}


class MMBaseStatedDevice(StandardReadable, Loggable):
    """Base for stated devices with a finite number of discrete positions.

    Provides a ``position`` signal and a ``num_positions`` config
    signal.  Subclasses set up hardware-specific labels and presets.

    Parameters
    ----------
    name : str
        MMCore device label.
    adapter_info : MMAdapterInfo
        Adapter and device identifiers.
    pre_init_props : dict | None
        Pre-init properties to set before ``initializeDevice``.
    num_positions : int
        Number of discrete positions (default ``8``).
    """

    def __init__(
        self,
        name: str,
        *,
        adapter_info: MMAdapterInfo,
        pre_init_props: dict | None = None,
        num_positions: int = 8,
    ) -> None:
        self.core = Core.instance()
        self.core.loadDevice(name, adapter_info.adapter, adapter_info.device)
        if pre_init_props:
            for prop, value in pre_init_props.items():
                self.core.setProperty(name, prop, str(value))
        self.core.initializeDevice(name)

        with self.add_children_as_readables():
            self.position = mm_property_signal(
                self.core, name, "State", datatype=int
            )

        with self.add_children_as_readables(StandardReadableFormat.CONFIG_SIGNAL):
            self.num_positions = soft_signal_rw(
                int, initial_value=num_positions
            )

    @property
    def labels(self) -> dict[int, str]:
        """Position → human-readable label mapping."""
        return {}

    def label_for(self, position: int) -> str:
        """Return the label for *position*, or ``str(position)``."""
        return self.labels.get(position, str(position))

    def position_for(self, label: str) -> int | None:
        """Return the position index for *label*, or ``None``."""
        for pos, lbl in self.labels.items():
            if lbl == label:
                return pos
        return None

    async def set_position(self, position: int) -> None:
        """Move the filter wheel to *position* (0-based index)."""
        num_positions = await self.num_positions.get_value()
        if not (0 <= position < num_positions):
            raise ValueError(
                f"Position {position} out of range "
                f"(0–{num_positions - 1})"
            )
        await self.position.set(position)
        self.logger.info("Moved to position %d (%s)", position, self.label_for(position))

    async def set_label(self, label: str) -> None:
        """Move the filter wheel to the position matching *label*."""
        pos = self.position_for(label)
        if pos is None:
            raise ValueError(
                f"Unknown label {label!r}. Available: {list(self.labels.values())}"
            )
        await self.set_position(pos)


class MMASIFWController(StandardReadable, Loggable):
    """ASI filter wheel controller (serial hub device).

    The controller manages serial communication with the physical
    hardware.  The filter wheel peripheral attaches to it.

    Parameters
    ----------
    name : str
        MMCore device label.
    port : str
        MMCore label of the pre-loaded ``SerialManager`` (default
        ``"COM3"``).
    """

    def __init__(self, name: str, *, port: str = "COM3") -> None:
        adapter_info = MMAdapterInfo(adapter="ASIFW1000", device="ASIFWController")
        self.core = Core.instance()
        self.core.loadDevice(name, adapter_info.adapter, adapter_info.device)
        self.core.setProperty(name, "Port", port)
        self.core.initializeDevice(name)

        with self.add_children_as_readables(StandardReadableFormat.CONFIG_SIGNAL):
            self.port = soft_signal_rw(str, initial_value=port)

        super().__init__(name=name)


class MMASIFilterWheel(MMBaseStatedDevice):
    """ASI 8-position filter wheel.

    Provides discrete position selection over 8 positions (0–7) with
    human-readable labels and colour-preset shortcuts that match the
    Spectra colour presets.

    Parameters
    ----------
    name : str
        MMCore device label.
    wheel_number : int
        Filter wheel number on the controller (default ``0``).
    """

    @property
    def labels(self) -> dict[int, str]:
        return dict(_FW_LABELS)

    @property
    def color_map(self) -> dict[str, int]:
        """Colour preset name → filter wheel position."""
        return dict(_FW_COLOR_FILTER_MAP)

    def __init__(
        self,
        name: str,
        *,
        wheel_number: int = 0,
        num_positions: int = 8,
    ) -> None:
        adapter_info = MMAdapterInfo(adapter="ASIFW1000", device="ASIFilterWheel")
        super().__init__(
            name,
            adapter_info=adapter_info,
            pre_init_props={"ASIFilterWheelNumber": str(wheel_number)},
            num_positions=num_positions,
        )
        StandardReadable.__init__(self, name=name)

    async def apply_color_preset(self, preset_name: str) -> None:
        """Move to the filter position matching a colour preset name.

        Valid names: ``"off"``, ``"brightfield"``, ``"514_teal"``,
        ``"640_red"``, ``"470_cyan"``, ``"561_green"``,
        ``"445_blue"``, ``"395_violet"``.
        """
        pos = self.color_map.get(preset_name)
        if pos is None:
            raise ValueError(
                f"Unknown colour preset {preset_name!r}. "
                f"Available: {sorted(self.color_map)}"
            )
        await self.set_position(pos)
