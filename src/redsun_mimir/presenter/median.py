from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
from event_model import DocumentRouter
from psygnal import SignalGroup
from redsun.log import Loggable
from redsun.presenter import Presenter
from redsun.virtual import Signal, slot
from redsun.writers import Writer, WriterError

from redsun_mimir.streams import MEDIAN_SCAN_STREAM

if TYPE_CHECKING:
    from collections.abc import Mapping

    import numpy.typing as npt
    from bluesky.protocols import Reading
    from event_model.documents import Event, EventDescriptor, RunStop, StreamResource
    from ophyd_async.core import Device
    from redsun.virtual import VirtualContainer

_MEDIAN_SUFFIX = "_median"
_FILTERED_SUFFIX = "_filtered"
_BUFFER_SUFFIX = "-buffer"


def _base_name(source: str) -> str:
    """Strip the buffer suffix off a data key: ``cam-buffer`` -> ``cam``."""
    return source.removesuffix(_BUFFER_SUFFIX)


class FrameSignals(SignalGroup, strict=True):
    """The frame streams a median presenter publishes.

    Grouping them keeps the two payloads the same shape: both carry a
    ``dict[str, Reading[Any]]`` keyed by the viewer layer the frame belongs to.
    """

    median = Signal(object)
    filtered = Signal(object)


class MedianPresenter(Presenter, DocumentRouter, Loggable):
    """Background-median filtering, driven entirely by documents.

    A square scan collects a stack of frames off-target; their per-pixel
    median along the time axis is the static background of the sample. Every
    subsequent live frame is divided by that median, which flattens out the
    fixed pattern and leaves the scattering signal.

    Both phases arrive as Event documents, so this presenter is a
    [`DocumentRouter`][event_model.DocumentRouter]:

    - frames on the `MEDIAN_SCAN_STREAM` are **cached**; when that run stops
      the median is computed, published on ``frames.median`` and written by a
      `Writer` into the store the acquisition names, under
      ``<detector>_median``, as soon as a run has named one;
    - frames on any other stream - in practice `LIVE_VIEW_STREAM`, produced
      by ``bps.monitor`` on the detector's buffer signal - are **divided** by
      the cached median and published on ``frames.filtered`` as their
      own viewer layer, leaving the raw layer untouched.

    All state is keyed by run, so concurrent or nested runs never mix. Every
    document reaches the writer before this presenter acts on it, except
    ``stop``, which reaches it after, so the median written there still
    finds its run open.

    Parameters
    ----------
    name : str
        Identity key of the presenter.
    devices : Mapping[str, Device]
        Available devices. Those exposing a ``buffer`` signal are tracked;
        anything else is ignored.

    Attributes
    ----------
    frames : FrameSignals
        The two frame streams this presenter publishes, ``median`` and
        ``filtered``. Both carry a ``dict[str, Reading[Any]]``.
    """

    def __init__(
        self,
        name: str,
        devices: Mapping[str, Device],
        /,
    ) -> None:
        super().__init__(name, devices)

        # instance=self so the container can name this presenter as the
        # publisher of either member rather than the group
        self.frames = FrameSignals(instance=self)

        #: data keys of the buffers whose frames this presenter takes
        self._sources: set[str] = {
            device.buffer.name
            for device in devices.values()
            if hasattr(device, "buffer")
        }

        #: writes each detector's median into the store its run names
        self._writer = Writer()
        for source in self._sources:
            detector = _base_name(source)
            self._writer.derive(f"{detector}{_MEDIAN_SUFFIX}", source=detector)

        #: latest median per source data key
        self.medians: dict[str, npt.NDArray[Any]] = {}

        # descriptor uid -> (run uid, sources) for the accumulating scan stream
        self._scan_streams: dict[str, tuple[str, list[str]]] = {}
        # descriptor uid -> sources for live streams that get corrected
        self._live_streams: dict[str, list[str]] = {}
        # (run uid, source) -> accumulated scan frames
        self._frames: dict[tuple[str, str], list[npt.NDArray[Any]]] = {}

    def register_providers(self, container: VirtualContainer) -> None:
        """Register this presenter as a signal owner and document callback."""
        container.register_signals(self)
        container.register_callbacks(self)

    def __call__(self, name: str, doc: dict[str, Any], validate: bool = False) -> Any:
        """Dispatch *doc* to the writer and to this presenter, ``stop`` last to the writer."""
        if name != "stop":
            self._writer(name, doc, validate)
        result = super().__call__(name, doc, validate)
        if name == "stop":
            self._writer(name, doc, validate)
        return result

    @slot
    def clear_medians(self, plan_name: str) -> None:
        """Forget every cached median: a new plan means a new background."""
        if self.medians:
            self.logger.debug(f"Clearing cached medians before {plan_name!r}")
        self.medians.clear()

    def shutdown(self) -> None:
        """Close what the writer left open, so every store stays readable."""
        self._writer.shutdown()

    def descriptor(self, doc: EventDescriptor) -> None:
        """Route a stream to the accumulate or the correct path."""
        sources = [key for key in doc["data_keys"] if key in self._sources]
        if not sources:
            return

        if doc.get("name") != MEDIAN_SCAN_STREAM:
            self._live_streams[doc["uid"]] = sources
            return

        self._scan_streams[doc["uid"]] = (doc["run_start"], sources)

    def stream_resource(self, doc: StreamResource) -> None:
        """Write a median computed before its store was named.

        A scan may run before the stream that writes the frames it corrects.
        """
        for source, median in self.medians.items():
            if _base_name(source) == doc["data_key"]:
                self._write(source, median)

    def event(self, doc: Event) -> Event:
        """Cache scan frames; correct live frames against the median."""
        scan = self._scan_streams.get(doc["descriptor"])
        if scan is not None:
            run, sources = scan
            for source in sources:
                if source in doc["data"]:
                    self._frames.setdefault((run, source), []).append(
                        np.asarray(doc["data"][source])
                    )
            return doc

        live = self._live_streams.get(doc["descriptor"])
        if live is not None:
            self._emit_filtered(doc, live)
        return doc

    def _emit_filtered(self, doc: Event, sources: list[str]) -> None:
        """Divide every live frame in *doc* by its median and publish it."""
        filtered: dict[str, Reading[Any]] = {}
        for source in sources:
            if source not in doc["data"]:
                continue
            median = self.medians.get(source)
            if median is None:
                # no background acquired yet: nothing to correct against
                continue
            frame = np.asarray(doc["data"][source])
            if median.shape != frame.shape:
                self.logger.warning(
                    f"Median for {source!r} has shape {median.shape}, "
                    f"incoming frame has {frame.shape}; skipping correction."
                )
                continue
            filtered[f"{_base_name(source)}{_FILTERED_SUFFIX}"] = {
                "value": np.divide(
                    frame,
                    median,
                    out=np.ones_like(frame, dtype=np.float32),
                    where=median != 0,
                ),
                "timestamp": doc["time"],
            }
        if filtered:
            self.frames.filtered.emit(filtered)

    def stop(self, doc: RunStop) -> None:
        """Compute, publish and write the median for every source of this run."""
        run = doc["run_start"]
        for (candidate, source), frames in list(self._frames.items()):
            if candidate != run:
                continue
            del self._frames[(candidate, source)]
            if not frames:
                continue

            stack = np.stack(frames, axis=0)
            median = np.median(stack, axis=0).astype(stack.dtype)
            self.medians[source] = median
            self.logger.debug(
                f"Median computed for {source!r}: "
                f"{len(frames)} frames, shape {median.shape}"
            )
            self.frames.median.emit(
                {
                    f"{_base_name(source)}{_MEDIAN_SUFFIX}": {
                        "value": median,
                        "timestamp": doc["time"],
                    }
                }
            )

            self._write(source, median)

        for uid, (candidate, _) in list(self._scan_streams.items()):
            if candidate == run:
                del self._scan_streams[uid]

    def _write(self, source: str, median: npt.NDArray[Any]) -> None:
        """Write the median into the store its detector's run names, if one has."""
        detector = _base_name(source)
        try:
            self._writer.write(
                f"{detector}{_MEDIAN_SUFFIX}",
                median,
                metadata={"derived_from": detector},
            )
        except WriterError as error:
            # a run that named no store yet is the usual case, a scan before
            # the stream; the median is kept and written once one is named
            self.logger.debug(f"Median for {detector!r} not written: {error}")
