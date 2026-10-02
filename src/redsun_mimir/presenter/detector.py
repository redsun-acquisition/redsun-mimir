from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any

from event_model import DocumentRouter
from psygnal import Signal
from redsun import DevicesOf, slot
from redsun.aio import run_coro
from redsun.log import Loggable

from redsun_mimir.common import Roi
from redsun_mimir.protocols import DetectorProtocol, HoldsDeferrals  # noqa: TC001

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from bluesky.protocols import Descriptor, Reading
    from event_model.documents import Event, EventDescriptor
    from ophyd_async.core import SignalRW
    from redsun.engine import Deferrals

    from redsun_mimir.protocols import LayerSpec


#: The settings a view may change, each named after the signal carrying it, so
#: a stray port name cannot reach an arbitrary attribute. ``pixel_dtype`` is
#: not among them: the camera reports it, nobody sets it.
def _writable_settings(detector: DetectorProtocol) -> dict[str, SignalRW[Any]]:
    """Return the detector's writable settings, keyed as the view names them.

    A key is the signal's data key without the device name prefix.
    """
    signals: list[SignalRW[Any]] = [
        detector.exposure,
        detector.roi,
        detector.pixel_dtype,
    ]
    properties: Mapping[str, SignalRW[str]] = getattr(detector, "properties", {})
    signals.extend(properties.values())
    return {signal.name.removeprefix(f"{detector.name}-"): signal for signal in signals}


class DetectorPresenter(DocumentRouter, Loggable):
    """Presenter for detector configuration and live data routing.

    Live frames arrive as Event documents, the plan having put each
    detector's buffer signal under `bps.monitor`, so every displayed frame
    is part of the run and ordered against its other documents. Frames are
    forwarded raw: [`MedianPresenter`][redsun_mimir.presenter.MedianPresenter]
    publishes the corrected ones on a signal of its own, as a separate layer.

    Parameters
    ----------
    timeout
        Timeout in seconds for async configuration calls; `None` means `1.0`.
    """

    sig_new_configuration = Signal(str, str, object)
    """Emitted after a detector setting is applied, with the detector name,
    the canonical key of the setting and its new value."""

    sig_new_data = Signal(object)
    """Emitted for every live frame carried by an Event document, as a
    `dict[str, Reading[Any]]`. Beside the `<detector>-buffer` reading travels
    `<detector>-roi`, a `Roi` naming the sensor region the frame was taken
    with."""

    def __init__(
        self,
        name: str,
        *,
        detectors: DevicesOf[DetectorProtocol],
        timeout: float | None = 1.0,
    ) -> None:
        super().__init__()
        self.name = name
        self.timeout = timeout or 1.0
        self.detectors = detectors
        #: buffer data keys this presenter forwards, by descriptor uid
        self._live_streams: dict[str, list[str]] = {}
        self._buffer_keys = {
            detector.buffer.name for detector in self.detectors.values()
        }
        self._detector_by_buffer = {
            detector.buffer.name: name for name, detector in self.detectors.items()
        }
        # the camera's properties come from its service, so they exist only
        # once it has connected, which the build does before presenters
        self._writable_settings = {
            name: _writable_settings(detector)
            for name, detector in self.detectors.items()
        }
        #: each detector's ROI as last reported, kept by subscription so a
        #: frame is forwarded with the region it was taken with
        self._rois: dict[str, Roi] = {}
        self._roi_callbacks: dict[str, Callable[[dict[str, Reading[Any]]], None]] = {}
        self._deferrals: Deferrals | None = None
        run_coro(self._subscribe_rois())

    async def _subscribe_rois(self) -> None:
        """Read every ROI once, then subscribe to it, on the subscription's loop.

        The read places the first frame: a subscription reports its first
        value only when the transport gets to it.
        """
        for name, detector in self.detectors.items():
            self._rois[name] = Roi.parse(await detector.roi.get_value())
            self._roi_callbacks[name] = partial(self._store_roi, name)
            detector.roi.subscribe(self._roi_callbacks[name])

    async def _unsubscribe_rois(self) -> None:
        for name, callback in self._roi_callbacks.items():
            self.detectors[name].roi.clear_sub(callback)
        self._roi_callbacks.clear()

    def shutdown(self) -> None:
        """Unsubscribe from the ROIs, so no subscription outlives the loop."""
        run_coro(self._unsubscribe_rois())

    def _store_roi(self, detector: str, reading: dict[str, Reading[Any]]) -> None:
        text = next(iter(reading.values()))["value"]
        # a PV subscription delivers the record's empty default before the
        # service has published a value; there is no ROI in it to remember
        if text:
            self._rois[detector] = Roi.parse(text)

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
            detector = self._detector_by_buffer[key]
            readings[f"{detector}-roi"] = {
                "value": self._rois.get(detector),
                "timestamp": doc["time"],
            }
            readings[key] = {"value": doc["data"][key], "timestamp": doc["time"]}
        if readings:
            self.sig_new_data.emit(readings)
        return doc

    def setup(self, plans: HoldsDeferrals | None = None) -> None:
        """Take the deferrals of the engine running the plans, if one does."""
        self._deferrals = None if plans is None else plans.plan_deferrals()

    def detector_layer_specs(self) -> dict[str, LayerSpec]:
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

    def detector_readings(self) -> dict[str, Reading[Any]]:
        """Return the configuration readings of every detector."""
        result: dict[str, Reading[Any]] = {}
        for device in self.detectors.values():
            result.update(run_coro(device.read_configuration()))
        return result

    def detector_descriptors(self) -> dict[str, Descriptor]:
        """Return the configuration descriptors of every detector.

        A setting this presenter cannot write has `:readonly` appended to
        its source, which the settings tree shows as a label.
        """
        result: dict[str, Descriptor] = {}
        for name, device in self.detectors.items():
            writable = {
                f"{name}-{key}" for key in self._writable_settings.get(name, {})
            }
            for key, descriptor in run_coro(device.describe_configuration()).items():
                if key not in writable:
                    descriptor = {
                        **descriptor,
                        "source": f"{descriptor['source']}:readonly",
                    }
                result[key] = descriptor
        return result

    @slot
    async def set(self, detector: str, property: str, value: Any) -> None:
        """Set a detector setting and announce the new value.

        *detector* is the bare device name and *property* the setting's key
        as the view names it; an unknown pair is logged and ignored. A ROI
        change is deferred to between two engine messages when the session
        has an engine.
        """
        obj = self._writable_settings.get(detector, {}).get(property)
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
            self.logger.info(f"{obj.name} set to {new_reading[obj.name]['value']!r}")
            self.sig_new_configuration.emit(
                detector, obj.name, new_reading[obj.name]["value"]
            )

        if property == "roi" and self._deferrals is not None:
            # a ROI applied inside a point would put frames of two shapes in
            # one event stream, so it is applied between two messages instead
            self._deferrals.request(apply)
            return
        await apply()
