"""Shuttered illumination devices (Lumencor Spectra)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ophyd_async.core import (
    AsyncStatus,
    StandardReadable,
    StandardReadableFormat,
    soft_signal_rw,
)
from pymmcore_plus import CMMCorePlus as Core
from redsun.log import Loggable

from ._backend import mm_property_signal
from ._common import MMAdapterInfo

if TYPE_CHECKING:
    from ophyd_async.core import SignalRW

_SPECTRA_CHANNELS = ("Cyan", "Red", "Violet", "Blue", "Teal", "Green")

_SPECTRA_POWER_LEVELS: dict[str, int] = {
    "Cyan": 0,
    "Red": 100,
    "Violet": 100,
    "Blue": 100,
    "Teal": 15,
    "Green": 0,
}

_SPECTRA_COLOR_PRESETS: dict[str, list[tuple[str, bool]]] = {
    "off": [
        ("Cyan", False), ("Red", False), ("Violet", False),
        ("Blue", False), ("Teal", False), ("Green", False),
    ],
    "brightfield": [
        ("Cyan", False), ("Red", False), ("Violet", False),
        ("Blue", False), ("Teal", False), ("Green", False),
    ],
    "514_teal": [
        ("Cyan", False), ("Red", False), ("Violet", False),
        ("Blue", False), ("Teal", True), ("Green", False),
    ],
    "640_red": [
        ("Cyan", False), ("Red", True), ("Violet", False),
        ("Blue", False), ("Teal", False), ("Green", False),
    ],
    "470_cyan": [
        ("Cyan", True), ("Red", False), ("Violet", False),
        ("Blue", False), ("Teal", False), ("Green", False),
    ],
    "561_green": [
        ("Cyan", False), ("Red", False), ("Violet", False),
        ("Blue", False), ("Teal", False), ("Green", True),
    ],
    "445_blue": [
        ("Cyan", False), ("Red", False), ("Violet", False),
        ("Blue", True), ("Teal", False), ("Green", False),
    ],
    "395_violet": [
        ("Cyan", False), ("Red", False), ("Violet", True),
        ("Blue", False), ("Teal", False), ("Green", False),
    ],
}


class MMBaseShutteredDevice(StandardReadable, Loggable):
    """Base for shuttered illumination devices (light engines).

    Provides ``enabled`` / ``intensity`` / ``wavelength`` / ``egu``
    signals and a ``trigger()`` method that toggles the shutter.
    Subclasses set up hardware-specific signals (channels, presets).

    Parameters
    ----------
    name : str
        MMCore device label.
    adapter_info : MMAdapterInfo
        Adapter and device identifiers.
    port : str
        MMCore label of the pre-loaded ``SerialManager`` device.
    setle_type : str
        Light engine type string for the ``SetLE_Type`` property.
    extra_pre_init : dict | None
        Additional pre-init properties beyond ``Port`` and
        ``SetLE_Type``.
    """

    def __init__(
        self,
        name: str,
        *,
        adapter_info: MMAdapterInfo,
        port: str,
        setle_type: str,
        extra_pre_init: dict | None = None,
    ) -> None:
        pre = {"Port": port, "SetLE_Type": setle_type}
        if extra_pre_init:
            pre.update(extra_pre_init)
        self.core = Core.instance()
        self.core.loadDevice(name, adapter_info.adapter, adapter_info.device)
        for prop, value in pre.items():
            self.core.setProperty(name, prop, str(value))
        self.core.initializeDevice(name)
        self.core.setShutterDevice(name)

        with self.add_children_as_readables():
            self.enabled = soft_signal_rw(bool, initial_value=False)
            self.intensity = soft_signal_rw(float, initial_value=0.0)

        with self.add_children_as_readables(StandardReadableFormat.CONFIG_SIGNAL):
            self.wavelength = soft_signal_rw(int, initial_value=0)
            self.egu = soft_signal_rw(str, initial_value="%")

    def trigger(self) -> AsyncStatus:
        """Toggle the shutter state."""
        async def _toggle():
            current = self.core.getShutterOpen(self.name)
            self.core.setShutterOpen(self.name, not current)
            await self.enabled.set(not current)

        return AsyncStatus(_toggle())


class MMSpectraShutteredDevice(MMBaseShutteredDevice):
    """Lumencor Spectra illumination source with six colour channels
    and preset configurations.

    Parameters
    ----------
    name : str
        MMCore device label.
    port : str
        MMCore label of the pre-loaded ``SerialManager`` (default
        ``"COM25"``).
    setle_type : str
        Lumencor engine type (default ``"SpectraX"``).
    """

    @property
    def channel_names(self) -> tuple[str, ...]:
        return _SPECTRA_CHANNELS

    @property
    def power_levels(self) -> dict[str, int]:
        return dict(_SPECTRA_POWER_LEVELS)

    @property
    def color_presets(self) -> dict[str, list[tuple[str, bool]]]:
        return {k: list(v) for k, v in _SPECTRA_COLOR_PRESETS.items()}

    def __init__(
        self,
        name: str,
        *,
        port: str = "COM25",
        setle_type: str = "SpectraX",
    ) -> None:
        adapter_info = MMAdapterInfo(adapter="LumencorSpectra", device="Spectra")
        super().__init__(
            name,
            adapter_info=adapter_info,
            port=port,
            setle_type=setle_type,
        )

        with self.add_children_as_readables():
            for ch in _SPECTRA_CHANNELS:
                setattr(
                    self,
                    f"{ch.lower()}_enable",
                    mm_property_signal(self.core, name, f"{ch}_Enable", datatype=str),
                )
                setattr(
                    self,
                    f"{ch.lower()}_level",
                    mm_property_signal(self.core, name, f"{ch}_Level", datatype=int),
                )

        StandardReadable.__init__(self, name=name)

    async def apply_preset(self, preset_name: str) -> None:
        """Apply a named colour preset (e.g. ``"470_cyan"``, ``"off"``).

        Each preset enables one channel and disables all others.
        Presets that carry a filter-wheel hint are handled by the
        acquisition layer.
        """
        preset = self.color_presets.get(preset_name)
        if preset is None:
            raise ValueError(
                f"Unknown preset {preset_name!r}. "
                f"Available: {sorted(self.color_presets)}"
            )
        for ch_name, enable in preset:
            sig: SignalRW = getattr(self, f"{ch_name.lower()}_enable")
            await sig.set("1" if enable else "0")
        self.logger.info("Applied colour preset: %s", preset_name)

    async def set_power(self, channel: str, level: int) -> None:
        """Set the power level for a single channel (0-100)."""
        if channel not in _SPECTRA_CHANNELS:
            raise ValueError(
                f"Unknown channel {channel!r}. "
                f"Available: {_SPECTRA_CHANNELS}"
            )
        sig: SignalRW = getattr(self, f"{channel.lower()}_level")
        await sig.set(level)
        self.logger.info("Set %s power level to %d", channel, level)

    async def apply_full_preset(
        self,
        preset_name: str,
        *,
        power_overrides: dict[str, int] | None = None,
    ) -> None:
        """Apply a colour preset and set each channel's power level.

        By default the power levels from ``dcam_fw.cfg`` are used.
        Pass ``power_overrides`` to override specific channels.
        """
        await self.apply_preset(preset_name)
        levels = dict(self.power_levels)
        if power_overrides:
            levels.update(power_overrides)
        for ch in _SPECTRA_CHANNELS:
            await self.set_power(ch, levels.get(ch, 0))
