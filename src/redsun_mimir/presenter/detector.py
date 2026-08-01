from __future__ import annotations

from typing import TYPE_CHECKING, Any

from bluesky.protocols import Descriptor  # noqa: TC002
from event_model import DocumentRouter
from redsun.aio import run_coro
from redsun.log import Loggable
from redsun.presenter import Presenter
from redsun.virtual import Signal, slot

from redsun_mimir.protocols import DetectorProtocol
from redsun_mimir.providers import (
    DETECTOR_DESCRIPTORS,
    DETECTOR_LAYER_SPECS,
    DETECTOR_READINGS,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bluesky.protocols import Reading
    from event_model.documents import Event, EventDescriptor
    from ophyd_async.core import Device, SignalRW
    from redsun.virtual import VirtualContainer

    from redsun_mimir.protocols import LayerSpec


#: Configuration properties a view may change, each named after the signal
#: that carries it on a detector. A whitelist, so a stray port name cannot
#: reach an arbitrary attribute.
_CONFIGURABLE = frozenset({"roi", "exposure", "pixel_dtype"})


class DetectorPresenter(Presenter, DocumentRouter, Loggable):
    """Presenter for detector configuration and live data routing.

    Live frames reach this presenter as Event documents - the plan puts each
    detector's buffer signal under ``bps.monitor`` - rather than through a
    direct ``subscribe_reading`` on the signal. Going through the document
    sequence keeps every displayed frame part of the run: it is ordered
    against the other documents, and any callback that reasons about the run
    sees it.

    Frames are forwarded **raw**. Background-median correction is
    [`MedianPresenter`][redsun_mimir.presenter.MedianPresenter]'s
    responsibility, and it publishes the corrected frames on its own signal
    so raw and filtered end up as separate viewer layers.

    Parameters
    ----------
    name :
        Identity key of the presenter.
    devices :
        Mapping of device names to device instances.
    timeout : float | None, keyword-only, optional
        Timeout in seconds for async configuration calls.
        Defaults to ``1.0``.

    Attributes
    ----------
    sig_new_configuration : Signal[str, str, object]
        Emitted after a detector setting is successfully applied.
        Carries the detector name (``str``), the canonical key of the
        changed setting (``str``) and its new value (``object``).
    sig_new_data : Signal[dict[str, Reading[Any]]]
        Emitted for every live frame carried by an Event document.
    """

    sig_new_configuration = Signal(str, str, object)
    sig_new_data = Signal(object)

    def __init__(
        self,
        name: str,
        devices: Mapping[str, Device],
        /,
        timeout: float | None = 1.0,
    ) -> None:
        super().__init__(name, devices)
        self.timeout = timeout or 1.0
        self.detectors: dict[str, DetectorProtocol] = {
            name: device
            for name, device in devices.items()
            if isinstance(device, DetectorProtocol)
        }
        #: buffer data keys this presenter forwards, by descriptor uid
        self._live_streams: dict[str, list[str]] = {}
        self._buffer_keys = {
            detector.buffer.name for detector in self.detectors.values()
        }

    def descriptor(self, doc: EventDescriptor) -> None:
        """Remember which streams carry a tracked detector's buffer."""
        keys = [key for key in doc["data_keys"] if key in self._buffer_keys]
        if keys:
            self._live_streams[doc["uid"]] = keys

    def event(self, doc: Event) -> Event:
        """Forward the raw frames of a live event to the viewer."""
        keys = self._live_streams.get(doc["descriptor"])
        if keys is None:
            return doc
        readings: dict[str, Reading[Any]] = {
            key: {"value": doc["data"][key], "timestamp": doc["time"]}
            for key in keys
            if key in doc["data"]
        }
        if readings:
            self.sig_new_data.emit(readings)
        return doc

    def register_providers(self, container: VirtualContainer) -> None:
        """Register detector info as providers in the DI container.

        Also registers detector signals in the container.
        """
        container.provide(DETECTOR_DESCRIPTORS, self.devices_description())
        container.provide(DETECTOR_READINGS, self.devices_configuration())
        container.provide(DETECTOR_LAYER_SPECS, self.layer_specs())
        container.register_signals(self)
        container.register_callbacks(self)

    def layer_specs(self) -> dict[str, LayerSpec]:
        """Get the layer specifications for all detector devices."""
        specs: dict[str, LayerSpec] = {}
        for device in self.detectors.values():
            roi = run_coro(device.roi.get_value())
            dtype = run_coro(device.pixel_dtype.get_value())
            specs[device.name] = {"shape": roi[2:], "dtype": dtype}
        return specs

    def devices_configuration(self) -> dict[str, Reading[Any]]:
        """Get the current configuration readings of all detector devices."""
        result: dict[str, Reading[Any]] = {}
        for device in self.detectors.values():
            result.update(run_coro(device.read_configuration()))
        return result

    def devices_description(self) -> dict[str, Descriptor]:
        """Get the configuration descriptors of all detector devices."""
        result: dict[str, Descriptor] = {}
        for device in self.detectors.values():
            result.update(run_coro(device.describe_configuration()))
        return result

    @slot
    async def set(self, detector: str, property: str, value: Any) -> None:
        """Set a detector configuration property and announce the new value.

        Parameters
        ----------
        detector : str
            Bare device name as emitted by the view.
        property : str
            Configuration key representing the setting to change.
        value : object
            New value for the setting.
        """
        if property not in _CONFIGURABLE:
            self.logger.error(f"Unknown property {property!r} for {detector!r}")
            return

        obj: SignalRW[Any] = getattr(self.detectors[detector], property)
        status = obj.set(value)
        await status
        if not status.success:
            self.logger.error(f"Failed to set {obj} to {value!r}: {status.exception()}")
            return
        new_reading = await obj.read()
        self.sig_new_configuration.emit(
            detector, obj.name, new_reading[obj.name]["value"]
        )
