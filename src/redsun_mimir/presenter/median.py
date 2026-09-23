from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
from event_model import DocumentRouter
from psygnal import SignalGroup
from redsun.log import Loggable
from redsun.presenter import Presenter
from redsun.virtual import Signal, slot
from redsun.writers import Writer, WriterError

from redsun_mimir.common import MEDIAN_SCAN_STREAM

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import TypedDict

    import numpy.typing as npt
    from bluesky.protocols import Reading
    from event_model.documents import Event, EventDescriptor, RunStop, StreamResource
    from ophyd_async.core import Device
    from redsun.virtual import VirtualContainer

    class FramePosition(TypedDict):
        """Where one frame of a scan's stack was taken."""

        frame_id: int
        """The frame's place in the stack, counted from one."""

        axes: dict[str, Any]
        """Every reading of the frame's event beside the frame itself, keyed
        as the event keys them, such as ``xystage-axis-x``."""

    #: One record per scan frame, in stack order.
    Positions = list[FramePosition]


_MEDIAN_SUFFIX = "_median"
_SCAN_SUFFIX = "_scan"
_FILTERED_SUFFIX = "_filtered"
_BUFFER_SUFFIX = "-buffer"


def plain(value: Any) -> Any:
    """Return *value* as a builtin, so a store's JSON metadata can hold it."""
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    return value


def _base_name(source: str) -> str:
    """Strip the buffer suffix off a data key, ``cam-buffer`` to ``cam``."""
    return source.removesuffix(_BUFFER_SUFFIX)


class FrameSignals(SignalGroup, strict=True):
    """The frame streams a median presenter publishes.

    Both carry a ``dict[str, Reading[Any]]`` keyed by viewer layer.
    """

    median = Signal(object)
    filtered = Signal(object)


class MedianPresenter(Presenter, DocumentRouter, Loggable):
    """Background-median filtering, driven by documents.

    A square scan collects a stack of frames off-target; their per-pixel
    median over time is the static background, and every later live frame
    is divided by it. Both phases arrive as Event documents, so this
    presenter is a [`DocumentRouter`][event_model.DocumentRouter]:

    - frames on the `MEDIAN_SCAN_STREAM` are cached, each with the readings
      that came in its event; when that run stops the median is published on
      ``frames.median`` and the stack is written under ``<detector>_scan``
      into the store the acquisition names, once a run has named one, with
      one record per frame naming the position it was taken at;
    - frames on any other stream, in practice `LIVE_VIEW_STREAM`, are divided
      by the cached median and published on ``frames.filtered`` as a layer
      of their own.

    State is keyed by run, so nested runs never mix. Every document reaches
    the writer before this presenter, except ``stop``, which reaches it
    after, so the stack written there still finds its run open.

    Parameters
    ----------
    devices : Mapping[str, Device]
        Only those exposing a ``buffer`` signal are tracked.

    Attributes
    ----------
    frames : FrameSignals
        The ``median`` and ``filtered`` streams, each carrying a
        ``dict[str, Reading[Any]]``.
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

        #: writes each detector's scan stack into the store its run names
        self._writer = Writer()
        for source in self._sources:
            detector = _base_name(source)
            self._writer.derive(f"{detector}{_SCAN_SUFFIX}", source=detector)

        #: latest median per source data key
        self.medians: dict[str, npt.NDArray[Any]] = {}
        #: the scan run, the stack and the positions each median came from,
        #: until a store takes them
        self._stacks: dict[str, tuple[str, npt.NDArray[Any], Positions]] = {}

        # descriptor uid -> (run uid, sources) for the accumulating scan stream
        self._scan_streams: dict[str, tuple[str, list[str]]] = {}
        # descriptor uid -> sources for live streams that get corrected
        self._live_streams: dict[str, list[str]] = {}
        # (run uid, source) -> accumulated scan frames
        self._frames: dict[tuple[str, str], list[npt.NDArray[Any]]] = {}
        # run uid -> one record per scan event, in the order they arrived
        self._positions: dict[str, Positions] = {}

    def register_providers(self, container: VirtualContainer) -> None:
        """Register this presenter as a signal owner and document callback."""
        container.register_signals(self)
        container.register_callbacks(self)

    def __call__(self, name: str, doc: dict[str, Any], validate: bool = False) -> Any:
        """Dispatch *doc* to the writer, then to this presenter.

        ``stop`` goes to the writer last, so its run is still open here.
        """
        if name != "stop":
            self._writer(name, doc, validate)
        result = super().__call__(name, doc, validate)
        if name == "stop":
            self._writer(name, doc, validate)
        return result

    @slot
    def clear_medians(self, plan_name: str) -> None:
        """Forget every cached median and stack before a new plan."""
        if self.medians:
            self.logger.debug(f"Clearing cached medians before {plan_name!r}")
        self.medians.clear()
        self._stacks.clear()

    def shutdown(self) -> None:
        """Close what the writer left open, so every store stays readable."""
        self._writer.shutdown()

    def descriptor(self, doc: EventDescriptor) -> None:
        """Route a stream to be accumulated or corrected."""
        sources = [key for key in doc["data_keys"] if key in self._sources]
        if not sources:
            return

        if doc.get("name") != MEDIAN_SCAN_STREAM:
            self._live_streams[doc["uid"]] = sources
            return

        self._scan_streams[doc["uid"]] = (doc["run_start"], sources)

    def stream_resource(self, doc: StreamResource) -> None:
        """Write any stack scanned before its store was named."""
        for source, (scan_run, stack, positions) in self._stacks.items():
            if _base_name(source) == doc["data_key"]:
                self._write(source, scan_run, stack, positions)

    def event(self, doc: Event) -> Event:
        """Cache scan frames; correct live frames against the median."""
        scan = self._scan_streams.get(doc["descriptor"])
        if scan is not None:
            run, sources = scan
            # the stream counts its own events, so the id is the frame's place
            # in the stack whatever the plan did between two of them
            axes: dict[str, Any] = {}
            for key, value in doc["data"].items():
                if key in sources:
                    self._frames.setdefault((run, key), []).append(np.asarray(value))
                elif key not in self._sources:
                    axes[key] = plain(value)
            if axes:
                self._positions.setdefault(run, []).append(
                    {"frame_id": doc["seq_num"], "axes": axes}
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
        """Publish the median of every source of this run and write its stack."""
        run = doc["run_start"]
        positions = self._positions.pop(run, [])
        for (candidate, source), frames in list(self._frames.items()):
            if candidate != run:
                continue
            del self._frames[(candidate, source)]
            if not frames:
                continue

            stack = np.stack(frames, axis=0)
            median = np.median(stack, axis=0).astype(stack.dtype)
            self.medians[source] = median
            self._stacks[source] = (run, stack, positions)
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

            self._write(source, run, stack, positions)

        for uid, (candidate, _) in list(self._scan_streams.items()):
            if candidate == run:
                del self._scan_streams[uid]

    def _write(
        self,
        source: str,
        scan_run: str,
        stack: npt.NDArray[Any],
        positions: Positions,
    ) -> None:
        """Write the stack of *scan_run* into the store its detector's run names.

        *positions* go with it under ``positions``, one record per frame in
        stack order, its ``frame_id`` and the ``axes`` it was taken at.
        Logged and skipped while no run has named a store.
        """
        detector = _base_name(source)
        try:
            self._writer.write(
                f"{detector}{_SCAN_SUFFIX}",
                stack,
                metadata={
                    "derived_from": detector,
                    "stream": MEDIAN_SCAN_STREAM,
                    "scan_run": scan_run,
                    "positions": positions,
                },
            )
        except WriterError as error:
            # a run that named no store yet is the usual case, a scan before
            # the stream; the stack is kept and written once one is named
            self.logger.debug(f"Scan stack for {detector!r} not written: {error}")
