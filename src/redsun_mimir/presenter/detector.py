from __future__ import annotations

from collections.abc import Sequence  # noqa: TC003
from functools import partial
from typing import TYPE_CHECKING, Any

import bluesky.plan_stubs as bps
import redsun.engine.plan_stubs as rps
from bluesky.utils import MsgGenerator  # noqa: TC002
from event_model import DocumentRouter
from ophyd_async.core import TriggerInfo
from psygnal import Signal
from redsun import DevicesOf, slot
from redsun.aio import run_coro
from redsun.engine import Deferrals  # noqa: TC002
from redsun.engine.actions import ActionManager, PlanAction, continuous
from redsun.log import Loggable

from redsun_mimir.common import LIVE_VIEW_STREAM, Roi
from redsun_mimir.plans import capture, prepare_and_declare
from redsun_mimir.protocols import DetectorProtocol, ReadableFlyer  # noqa: TC001

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from bluesky.protocols import Descriptor, Reading
    from event_model.documents import Event, EventDescriptor
    from ophyd_async.core import SignalRW
    from redsun import PlanEntry

    from redsun_mimir.protocols import LayerSpec

#: The action of `live_stream` writing frames to disk.
STREAM = PlanAction(
    name="stream",
    description="Toggle data streaming to disk.",
    toggle_states=("start", "stop"),
)


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

    It offers `live_stream`, and holds as `actions` the `ActionManager` that
    plan waits on.
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
        self.actions = ActionManager()
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

    def setup(self, deferrals: Deferrals | None = None) -> None:
        """Take the deferrals of the engine running the plans, if a component shares them."""
        self._deferrals = deferrals

    def plan_map(self) -> Mapping[str, PlanEntry]:
        """Return the plan this presenter offers."""
        return {"live_stream": {"plan": self.live_stream}}

    @continuous
    def live_stream(
        self,
        detectors: Sequence[ReadableFlyer],
        frames: int = 10,
        write_forever: bool = False,
        /,
        stream: PlanAction = STREAM,
    ) -> MsgGenerator[None]:
        """Perform live data collection and optionally store data to disk.

        The `stream` action streams the acquired frames to a Zarr store for
        `frames` frames, as a run nested in this one whose start document
        names this run as `parent`. Live visualization continues meanwhile.

        Parameters
        ----------
        detectors
            The detectors to collect from.
        frames
            The number of frames to stream to disk.
        write_forever
            Stream until the `stream` action is released, ignoring `frames`.
        """
        stream_name = "live_stream"
        trigger_info = TriggerInfo(number_of_events=0 if write_forever else frames)

        parent = yield from bps.open_run()

        # live visualization travels as Event documents, so the viewer sees
        # frames through the same document sequence as everything else
        for det in detectors:
            yield from bps.monitor(det.buffer, name=LIVE_VIEW_STREAM)

        while True:
            # preparing starts the live view and hands each detector the
            # store its next capture writes; the capture declares it
            yield from bps.stage_all(*detectors)
            yield from prepare_and_declare(
                detectors, trigger_info, stream_name, declare=False
            )
            name = yield from self.actions.wait(stream)
            try:
                names = ", ".join(det.name for det in detectors)
                self.logger.info(f"live_stream: writing {names} to disk")
                yield from rps.lock_wrapper(
                    capture(
                        detectors,
                        stream_name,
                        parent=parent,
                        until=(
                            self.actions.wait_released(stream)
                            if write_forever
                            else None
                        ),
                    ),
                    *detectors,
                )
                self.logger.info(f"live_stream: finished writing {names}")
            finally:
                self.actions.done(name)

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
