from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any

from bluesky.protocols import Descriptor  # noqa: TC002
from event_model import DocumentRouter
from redsun.aio import run_coro
from redsun.engine import DEFERRALS
from redsun.log import Loggable
from redsun.presenter import Presenter
from redsun.virtual import Signal, slot

from redsun_mimir.common import Roi
from redsun_mimir.protocols import DetectorProtocol
from redsun_mimir.providers import (
    DETECTOR_DESCRIPTORS,
    DETECTOR_LAYER_SPECS,
    DETECTOR_READINGS,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from bluesky.protocols import Reading
    from event_model.documents import Event, EventDescriptor
    from ophyd_async.core import Device, SignalRW
    from redsun.engine import Deferrals
    from redsun.virtual import VirtualContainer

    from redsun_mimir.protocols import LayerSpec


#: The settings a view may change, each named after the signal carrying it, so
#: a stray port name cannot reach an arbitrary attribute. ``pixel_dtype`` is
#: not among them: the camera reports it, nobody sets it.
def _settable_signals(detector: DetectorProtocol) -> dict[str, SignalRW[Any]]:
    """Return the detector's writable settings, keyed as the view names them.

    A key is the signal's data key without the device name prefix.
    """
    signals: list[SignalRW[Any]] = [detector.exposure, detector.roi]
    properties: Mapping[str, SignalRW[str]] = getattr(detector, "properties", {})
    signals.extend(properties.values())
    return {signal.name.removeprefix(f"{detector.name}-"): signal for signal in signals}


class DetectorPresenter(Presenter, DocumentRouter, Loggable):
    """Presenter for detector configuration and live data routing.

    Live frames arrive as Event documents, the plan having put each
    detector's buffer signal under ``bps.monitor``, so every displayed frame
    is part of the run and ordered against its other documents. Frames are
    forwarded raw: [`MedianPresenter`][redsun_mimir.presenter.MedianPresenter]
    publishes the corrected ones on a signal of its own, as a separate layer.

    Parameters
    ----------
    timeout : float | None, optional
        Timeout in seconds for async configuration calls; ``None`` means ``1.0``.

    Attributes
    ----------
    sig_new_configuration : Signal[str, str, object]
        Emitted after a detector setting is applied, with the detector name,
        the canonical key of the setting and its new value.
    sig_new_data : Signal[dict[str, Reading[Any]]]
        Emitted for every live frame carried by an Event document. Beside the
        ``<detector>-buffer`` reading travels ``<detector>-roi``, a `Roi`
        naming the sensor region the frame was taken with.
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
        self._detector_of = {
            detector.buffer.name: name for name, detector in self.detectors.items()
        }
        #: each detector's ROI as last reported, kept by subscription so a
        #: frame is forwarded with the region it was taken with
        self._rois: dict[str, Roi] = {}
        self._roi_callbacks: dict[str, Callable[[dict[str, Reading[Any]]], None]] = {}
        self._deferrals: Deferrals | None = None
        run_coro(self._follow_rois())

    async def _follow_rois(self) -> None:
        """Read every ROI once, then subscribe to it, on the subscription's loop.

        The read places the first frame: a subscription reports its first
        value only when the transport gets to it.
        """
        for name, detector in self.detectors.items():
            self._rois[name] = Roi.parse(await detector.roi.get_value())
            self._roi_callbacks[name] = partial(self._remember_roi, name)
            detector.roi.subscribe(self._roi_callbacks[name])

    async def _unfollow_rois(self) -> None:
        for name, callback in self._roi_callbacks.items():
            self.detectors[name].roi.clear_sub(callback)
        self._roi_callbacks.clear()

    def shutdown(self) -> None:
        """Stop following the ROIs, so no subscription outlives the loop."""
        run_coro(self._unfollow_rois())

    def _remember_roi(self, detector: str, reading: dict[str, Reading[Any]]) -> None:
        self._rois[detector] = Roi.parse(next(iter(reading.values()))["value"])
        # the camera's properties come from its service, so they exist only
        # once it has connected, which the build does before presenters
        self._settables = {
            name: _settable_signals(detector)
            for name, detector in self.detectors.items()
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
        readings: dict[str, Reading[Any]] = {}
        for key in keys:
            if key not in doc["data"]:
                continue
            detector = self._detector_of[key]
            readings[f"{detector}-roi"] = {
                "value": self._rois.get(detector),
                "timestamp": doc["time"],
            }
            readings[key] = {"value": doc["data"][key], "timestamp": doc["time"]}
        if readings:
            self.sig_new_data.emit(readings)
        return doc

    def register_providers(self, container: VirtualContainer) -> None:
        """Register detector info, signals and callbacks with the container."""
        container.provide(DETECTOR_DESCRIPTORS, self.devices_description())
        container.provide(DETECTOR_READINGS, self.devices_configuration())
        container.provide(DETECTOR_LAYER_SPECS, self.layer_specs())
        container.register_signals(self)
        container.register_callbacks(self)

    def inject_dependencies(self, container: VirtualContainer) -> None:
        """Take the engine's deferrals, if a presenter here owns an engine."""
        self._deferrals = container.try_require(DEFERRALS)

    def layer_specs(self) -> dict[str, LayerSpec]:
        """Return the layer spec of every detector.

        A layer is the size of the sensor, whatever the ROI: a cropped frame
        is drawn into the rectangle its ROI names.
        """
        specs: dict[str, LayerSpec] = {}
        for device in self.detectors.values():
            width, height = run_coro(device.sensor_size.get_value())
            dtype = run_coro(device.pixel_dtype.get_value())
            specs[device.name] = {"shape": (int(height), int(width)), "dtype": dtype}
        return specs

    def devices_configuration(self) -> dict[str, Reading[Any]]:
        """Return the configuration readings of every detector."""
        result: dict[str, Reading[Any]] = {}
        for device in self.detectors.values():
            result.update(run_coro(device.read_configuration()))
        return result

    def devices_description(self) -> dict[str, Descriptor]:
        """Return the configuration descriptors of every detector."""
        result: dict[str, Descriptor] = {}
        for device in self.detectors.values():
            result.update(run_coro(device.describe_configuration()))
        return result

    @slot
    async def set(self, detector: str, property: str, value: Any) -> None:
        """Set a detector setting and announce the new value.

        *detector* is the bare device name and *property* the setting's key
        as the view names it; an unknown pair is logged and ignored. A ROI
        change is deferred to between two engine messages when the session
        has an engine.
        """
        obj = self._settables.get(detector, {}).get(property)
        if obj is None:
            self.logger.error(f"Unknown property {property!r} for {detector!r}")
            return

        async def apply() -> None:
            try:
                await obj.set(value)
            except Exception as error:  # noqa: BLE001 - the view is told, the loop goes on
                self.logger.error(f"Failed to set {obj.name} to {value!r}: {error}")
                return
            new_reading = await obj.read()
            self.sig_new_configuration.emit(
                detector, obj.name, new_reading[obj.name]["value"]
            )

        if property == "roi" and self._deferrals is not None:
            # a ROI applied inside a point would put frames of two shapes in
            # one event stream, so it lands between two messages instead
            self._deferrals.request(apply)
            return
        await apply()
