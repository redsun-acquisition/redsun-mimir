from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
from event_model import DocumentRouter
from psygnal import SignalGroup
from redsun.log import Loggable
from redsun.presenter import Presenter
from redsun.storage import StoreStateError, StreamSpec
from redsun.virtual import Signal, slot

from redsun_mimir.streams import MEDIAN_SCAN_STREAM

if TYPE_CHECKING:
    from collections.abc import Mapping

    import numpy.typing as npt
    from bluesky.protocols import Reading
    from event_model.documents import Event, EventDescriptor, RunStop
    from ophyd_async.core import Device
    from redsun.storage import BaseStorage, FrameSink
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
      the median is computed, published on ``frames.median`` and written to
      the detector's store through a capacity-1 sink;
    - frames on any other stream - in practice `LIVE_VIEW_STREAM`, produced
      by ``bps.monitor`` on the detector's buffer signal - are **divided** by
      the cached median and published on ``frames.filtered`` as their
      own viewer layer, leaving the raw layer untouched.

    All state is keyed by run, so concurrent or nested runs never mix.

    Parameters
    ----------
    name : str
        Identity key of the presenter.
    devices : Mapping[str, Device]
        Available devices. Those exposing both a ``buffer`` signal and a
        ``storage`` are tracked; anything else is ignored.

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

        #: buffer data key -> storage the median is written to
        self._storages: dict[str, BaseStorage] = {
            device.buffer.name: device.storage
            for device in devices.values()
            if hasattr(device, "buffer") and hasattr(device, "storage")
        }

        #: latest median per source data key
        self.medians: dict[str, npt.NDArray[Any]] = {}

        # descriptor uid -> (run uid, sources) for the accumulating scan stream
        self._scan_streams: dict[str, tuple[str, list[str]]] = {}
        # descriptor uid -> sources for live streams that get corrected
        self._live_streams: dict[str, list[str]] = {}
        # (run uid, source) -> accumulated scan frames
        self._frames: dict[tuple[str, str], list[npt.NDArray[Any]]] = {}
        # (run uid, source) -> sink the median is written through
        self._sinks: dict[tuple[str, str], FrameSink] = {}

    def register_providers(self, container: VirtualContainer) -> None:
        """Register this presenter as a signal owner and document callback."""
        container.register_signals(self)
        container.register_callbacks(self)

    @slot
    def clear_medians(self, plan_name: str) -> None:
        """Forget every cached median: a new plan means a new background."""
        if self.medians:
            self.logger.debug(f"Clearing cached medians before {plan_name!r}")
        self.medians.clear()

    def descriptor(self, doc: EventDescriptor) -> None:
        """Route a stream to the accumulate or the correct path."""
        sources = [key for key in doc["data_keys"] if key in self._storages]
        if not sources:
            return

        if doc.get("name") != MEDIAN_SCAN_STREAM:
            self._live_streams[doc["uid"]] = sources
            return

        run = doc["run_start"]
        self._scan_streams[doc["uid"]] = (run, sources)
        for source in sources:
            spec = self._spec_for(source, doc["data_keys"][source])
            if spec is None:
                continue
            storage = self._storages[source]
            try:
                storage.register(spec)
            except StoreStateError:
                # register is only legal before the backend opens; a store
                # already opened by a write burst cannot take a new key, so
                # the median is still computed and shown, just not written
                self.logger.warning(
                    f"Store for {source!r} is already open; the median will not "
                    "be written. Run the scan before streaming to disk."
                )
                continue
            self._sinks[(run, source)] = storage.sink(spec.data_key)

    def _spec_for(self, source: str, data_key: Mapping[str, Any]) -> StreamSpec | None:
        """Build the median `StreamSpec` from the source's data key."""
        raw_shape = data_key.get("shape") or []
        dims = [int(dim) for dim in raw_shape if dim is not None]
        if len(dims) != 2:
            self.logger.warning(
                f"Cannot derive a median stream for {source!r}: "
                f"expected a 2D shape, got {raw_shape!r}."
            )
            return None
        return StreamSpec(
            data_key=f"{_base_name(source)}{_MEDIAN_SUFFIX}",
            shape=(dims[0], dims[1]),
            dtype=np.dtype(data_key.get("dtype_numpy", "<u2")).name,
            capacity=1,
        )

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

            sink = self._sinks.pop((run, source), None)
            if sink is not None:
                # put_nowait is the sync face: safe from a callback thread
                sink.put_nowait(median)
                sink.close()

        for uid, (candidate, _) in list(self._scan_streams.items()):
            if candidate == run:
                del self._scan_streams[uid]
