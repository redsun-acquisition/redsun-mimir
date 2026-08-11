from __future__ import annotations

from typing import TYPE_CHECKING

from ophyd_async.core import (
    AsyncStatus,
    StandardReadable,
    StandardReadableFormat,
    soft_signal_r_and_setter,
    soft_signal_rw,
)
from pymmcore_plus import CMMCorePlus as Core
from redsun.log import Loggable

from ._backend import POLL_PERIOD, mm_value_signal
from ._common import MMAdapterInfo

if TYPE_CHECKING:
    from ophyd_async.core import SignalRW


class MMBaseShutteredDevice(StandardReadable, Loggable):
    """Micro-Manager light engine driving several illumination channels.

    Loads the engine and registers it as the core's shutter device. The
    channels themselves are separate devices: each one names this engine's
    label and is built after it.

    Parameters
    ----------
    name : str
        MMCore device label.
    adapter_info : MMAdapterInfo
        Adapter and device identifiers.
    port : str
        MMCore label of the serial port device to communicate over.
    pre_init_props : Mapping[str, str] | None
        Properties to write before ``initializeDevice``, beyond ``Port``.
    """

    def __init__(
        self,
        name: str,
        *,
        adapter_info: MMAdapterInfo,
        port: str,
        pre_init_props: dict[str, str] | None = None,
    ) -> None:
        self.core = Core.instance()
        self.core.loadDevice(name, adapter_info.adapter, adapter_info.device)
        self.core.setProperty(name, "Port", port)
        for prop, value in (pre_init_props or {}).items():
            self.core.setProperty(name, prop, value)
        self.core.initializeDevice(name)
        self.core.setShutterDevice(name)

        with self.add_children_as_readables():
            self.open = soft_signal_rw(
                bool,
                initial_value=False,
                getter=lambda: self.core.getShutterOpen(name),
                setter=lambda value: self.core.setShutterOpen(name, bool(value)),
                poll_period=POLL_PERIOD,
            )

        with self.add_children_as_readables(StandardReadableFormat.CONFIG_SIGNAL):
            self.port = soft_signal_rw(str, initial_value=port)

        super().__init__(name)

    @AsyncStatus.wrap
    async def trigger(self) -> None:
        """Toggle the shutter."""
        current = await self.open.get_value()
        await self.open.set(not current)
        self.logger.debug(
            f"{'Opened' if not current else 'Closed'} shutter {self.name}"
        )


class MMSpectraShutteredDevice(MMBaseShutteredDevice):
    """Lumencor Spectra light engine.

    Parameters
    ----------
    name : str
        MMCore device label.
    port : str
        MMCore label of the serial port device to communicate over.
    engine_type : str
        Engine variant, written to the adapter's ``SetLE_Type`` property.
    """

    def __init__(
        self,
        name: str,
        *,
        port: str,
        engine_type: str = "SpectraX",
    ) -> None:
        adapter_info = MMAdapterInfo(adapter="LumencorSpectra", device="Spectra")
        super().__init__(
            name,
            adapter_info=adapter_info,
            port=port,
            pre_init_props={"SetLE_Type": engine_type},
        )


class MMSpectraChannel(StandardReadable, Loggable):
    """One colour channel of a Lumencor Spectra light engine.

    The engine named by *engine* must already be loaded: build the
    [`MMSpectraShutteredDevice`][redsun_mimir.device.mmcore.MMSpectraShutteredDevice]
    first. Intensity is the channel's power level, in percent.

    Parameters
    ----------
    name : str
        Device name.
    engine : str
        MMCore label of the light engine this channel belongs to.
    channel : str
        Channel name as the adapter spells it, e.g. ``"Cyan"``.
    wavelength : int
        Wavelength of the channel in nanometres.
    """

    intensity: SignalRW[int | float]

    def __init__(
        self,
        name: str,
        /,
        engine: str,
        channel: str,
        wavelength: int = 0,
    ) -> None:
        self.core = Core.instance()
        enable = self.core.getPropertyObject(engine, f"{channel}_Enable")

        with self.add_children_as_readables():
            self.intensity = mm_value_signal(
                self.core, engine, f"{channel}_Level", int, name="intensity", units="%"
            )
            # the adapter spells the channel state as "0"/"1"; bool("0") is
            # True, so the raw string has to go through int first
            self.enabled = soft_signal_rw(
                bool,
                initial_value=False,
                getter=lambda: bool(int(enable.value)),
                setter=lambda value: enable.setValue("1" if value else "0"),
                poll_period=POLL_PERIOD,
            )

        with self.add_children_as_readables(StandardReadableFormat.CONFIG_SIGNAL):
            self.wavelength, _ = soft_signal_r_and_setter(int, initial_value=wavelength)
            self.binary, _ = soft_signal_r_and_setter(bool, initial_value=False)

        super().__init__(name)

    @AsyncStatus.wrap
    async def trigger(self) -> None:
        """Toggle the activation status of the channel."""
        current = await self.enabled.get_value()
        await self.enabled.set(not current)
        self.logger.debug(
            f"{'Enabled' if not current else 'Disabled'} light source {self.name}"
        )
