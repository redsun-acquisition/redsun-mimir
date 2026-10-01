from __future__ import annotations

from collections.abc import Sequence  # noqa: TC003
from typing import TYPE_CHECKING, Any

import bluesky.plan_stubs as bps
import numpy as np
import redsun.engine.plan_stubs as rps
from bluesky.preprocessors import set_run_key_decorator
from bluesky.utils import MsgGenerator  # noqa: TC002
from event_model import DocumentRouter
from ophyd_async.core import TriggerInfo
from psygnal import Signal, SignalGroup
from redsun import DevicesOf, slot
from redsun.engine.actions import ActionManager, PlanAction, continuous
from redsun.log import Loggable
from redsun.writers import Writer, WriterError

from redsun_mimir.common import LIVE_VIEW_STREAM, MEDIAN_SCAN_STREAM
from redsun_mimir.plans import capture, prepare_and_declare
from redsun_mimir.protocols import (  # noqa: TC001
    HasBuffer,
    MotorProtocol,
    ReadableFlyer,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import TypedDict

    import numpy.typing as npt
    from bluesky.protocols import Reading
    from event_model.documents import Event, EventDescriptor, RunStop, StreamResource
    from redsun import PlanEntry

    class FramePosition(TypedDict):
        """Where one frame of a scan's stack was taken."""

        frame_id: int
        """The frame's place in the stack, counted from one."""

        axes: dict[str, Any]
        """Every reading of the frame's event beside the frame itself, keyed
        as the event keys them, such as ``xystage-axis-x``."""

    #: One record per scan frame, in stack order.
    Positions = list[FramePosition]


#: Run key giving the background scan a document cycle of its own, apart from
#: the enclosing live run.
_MEDIAN_RUN_KEY = "median_scan"

_MEDIAN_SUFFIX = "_median"
_SCAN_SUFFIX = "_scan"
_FILTERED_SUFFIX = "_filtered"
_BUFFER_SUFFIX = "-buffer"

#: The action of `live_median_scan` scanning the background.
SCAN = PlanAction(name="scan", description="Trigger a scan movement.")

#: The action of `live_median_scan` writing a fixed number of frames to disk.
STREAM_ONCE = PlanAction(name="stream", description="Stream frames to disk.")


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


class MedianPresenter(DocumentRouter, Loggable):
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

    It offers the plan feeding it, `live_median_scan`, and lists itself as
    that plan's callback, so every run of the plan reaches it.

    State is keyed by run, so nested runs never mix. Every document reaches
    the writer before this presenter, except `stop`, which reaches it
    after, so the stack written there still finds its run open.
    """

    def __init__(self, name: str, *, sources: DevicesOf[HasBuffer]) -> None:
        super().__init__()
        self.name = name
        self.actions = ActionManager()

        # instance=self so the session can name this presenter as the
        # publisher of either member rather than the group
        self.frames = FrameSignals(instance=self)
        """The `median` and `filtered` streams, each carrying a
        `dict[str, Reading[Any]]`."""

        #: data keys of the buffers whose frames this presenter takes
        self._sources = {source.buffer.name for source in sources.values()}

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
        #: sources whose kept stack no store has received yet
        self._unwritten: set[str] = set()

        # descriptor uid -> (run uid, sources) for the accumulating scan stream
        self._scan_streams: dict[str, tuple[str, list[str]]] = {}
        # descriptor uid -> sources for live streams that get corrected
        self._live_streams: dict[str, list[str]] = {}
        # (run uid, source) -> accumulated scan frames
        self._frames: dict[tuple[str, str], list[npt.NDArray[Any]]] = {}
        # run uid -> one record per scan event, in the order they arrived
        self._positions: dict[str, Positions] = {}

    def plan_map(self) -> Mapping[str, PlanEntry]:
        """Return the plan this presenter offers, with itself as its callback."""
        return {
            "live_median_scan": {"plan": self.live_median_scan, "callbacks": [self]}
        }

    @continuous
    def live_median_scan(
        self,
        detectors: Sequence[ReadableFlyer],
        motor: MotorProtocol,
        step: float = 5.0,
        scan_frames: int = 40,
        stream_frames: int = 10,
        /,
        scan: PlanAction = SCAN,
        stream: PlanAction = STREAM_ONCE,
    ) -> MsgGenerator[None]:
        """Perform live data collection with temporal median filtering.

        Detectors emit frames at their live-view rate from the start. The
        `scan` action moves the motor in a square over x and y, collecting
        `scan_frames / 4` frames per side; this presenter computes their
        median when that run ends. The `stream` action flies the detectors to
        disk for `stream_frames` frames, as a run nested in this one whose
        start document names this run as `parent` and the last scan's run as
        `median_scan`; this presenter writes that scan's stack into the store
        the capture names.

        Parameters
        ----------
        detectors
            The detectors to collect from.
        motor
            The motor to scan with. Must expose `x` and `y` axes.
        step
            The motor step per frame, in the motor's units.
        scan_frames
            The number of frames to collect for the median, a quarter of
            them per side of the square.
        stream_frames
            The number of frames to stream to disk per `stream` action.

        Raises
        ------
        TypeError
            If `motor` does not expose `x` and `y` axes.
        """
        if not {"x", "y"}.issubset(motor.axis.keys()):
            raise TypeError(
                "The provided motor must expose 'x' and 'y' MotorAxis attributes."
            )

        live_stream = "live_stream"
        stream_prepare_info = TriggerInfo(number_of_events=stream_frames)

        restage = True
        scan_run: str | None = None

        parent = yield from bps.open_run()

        # every live frame travels as an Event document so this presenter
        # can divide it by the background median and publish the result
        for det in detectors:
            yield from bps.monitor(det.buffer, name=LIVE_VIEW_STREAM)

        while True:
            if restage:
                # preparing starts the live view and hands each detector the
                # store its next capture writes; the capture declares it
                yield from bps.stage_all(*detectors)
                yield from prepare_and_declare(
                    detectors, stream_prepare_info, live_stream, declare=False
                )
                restage = False

            name = yield from self.actions.wait(scan, stream)
            try:
                if name == scan.name:
                    scan_run = yield from rps.lock_wrapper(
                        self.square_scan(
                            detectors, motor, step, scan_frames // 4, parent=parent
                        ),
                        motor,
                        *detectors,
                    )
                else:
                    self.logger.debug("Start writing")
                    yield from rps.lock_wrapper(
                        capture(
                            detectors, live_stream, parent=parent, median_scan=scan_run
                        ),
                        *detectors,
                    )
                    restage = True
                    self.logger.debug("Writing complete")
            finally:
                self.actions.done(name)

    @set_run_key_decorator(_MEDIAN_RUN_KEY)  # type: ignore[untyped-decorator]
    def square_scan(
        self,
        detectors: Sequence[ReadableFlyer],
        motor: MotorProtocol,
        step: float,
        frames_per_side: int,
        *,
        parent: str | None = None,
    ) -> MsgGenerator[str]:
        """Collect a background stack by moving the motor in a square.

        The stack is emitted as Event documents in a nested run, so this
        presenter can accumulate the frames and compute the median when that
        run stops. The sides are x, y, -x, -y, with *frames_per_side* frames
        along each. A frame is taken where the motor already stands and before
        every move, so the stack starts at the position the scan was asked
        from and the last move closes the square back onto it. Every frame
        goes in an event of its own, with the axis positions it was taken at;
        the event's `seq_num` is the frame's place in the stack, the
        `frame_id` those positions are written under. The frames taken are
        shown as a progress scope named after the `scan` action. Returns the
        run's uid.

        Parameters
        ----------
        parent
            The uid of the run this scan serves, recorded on its start
            document.
        """
        x = motor.axis["x"]
        y = motor.axis["y"]

        uid: str = yield from bps.open_run(
            md={"purpose": MEDIAN_SCAN_STREAM, "parent": parent}
        )
        square = [
            (axis, direction)
            for axis, direction in ((x, step), (y, step), (x, -step), (y, -step))
            for _ in range(frames_per_side)
        ]
        yield from rps.declare_progress(SCAN.name)
        for frame, (axis, direction) in enumerate(square, start=1):
            # a detector taking frames continuously has one ready from
            # before the previous move; triggering waits for the one taken
            # where the motor stands now
            for det in detectors:
                yield from bps.trigger(det, wait=True)
            yield from bps.create(name=MEDIAN_SCAN_STREAM)
            for det in detectors:
                yield from bps.read(det.buffer)
            # the axes go in the same event, so each frame carries the
            # position it was taken at
            yield from bps.read(motor)
            yield from bps.save()
            yield from rps.update_progress(
                SCAN.name, current=frame, initial=0, target=len(square), unit="frames"
            )
            self.logger.debug(
                f"Frame {frame}/{len(square)} taken; "
                f"moving {axis.name} by {direction} steps."
            )
            yield from bps.mvr(axis, direction)
        yield from rps.update_progress(SCAN.name, done=True)
        yield from bps.close_run()
        return uid

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
        self._warn_unwritten(f"{plan_name!r} started before any capture")
        self.medians.clear()
        self._stacks.clear()

    def shutdown(self) -> None:
        """Close what the writer left open, so every store stays readable."""
        self._warn_unwritten("the session closed before any capture")
        self._writer.shutdown()

    def _warn_unwritten(self, reason: str) -> None:
        """Warn about every kept stack no store received, then forget them."""
        for source in sorted(self._unwritten):
            self.logger.warning(
                f"Scan stack for {_base_name(source)!r} never written: {reason}"
            )
        self._unwritten.clear()

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
            self._unwritten.add(source)
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
        else:
            self._unwritten.discard(source)
