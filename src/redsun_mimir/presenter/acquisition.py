from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from typing import TYPE_CHECKING

import bluesky.plan_stubs as bps
import redsun.engine.plan_stubs as rps
from bluesky.preprocessors import set_run_key_decorator
from bluesky.utils import MsgGenerator, RequestAbort
from ophyd_async.core import Device, TriggerInfo
from redsun.engine import DEFERRALS, Deferrals, RunEngine
from redsun.engine.actions import Action, continous
from redsun.log import Loggable
from redsun.presenter import Presenter
from redsun.presenter.plan_spec import (
    PlanSpec,
    UnresolvableAnnotationError,
    collect_arguments,
    create_plan_spec,
    resolve_arguments,
)
from redsun.virtual import Signal, slot

from redsun_mimir.common import LIVE_VIEW_STREAM, MEDIAN_SCAN_STREAM, DeviceLocks
from redsun_mimir.protocols import (  # noqa: TC001
    MotorProtocol,
    ReadableFlyer,
)
from redsun_mimir.providers import PLAN_SPECS

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from concurrent.futures import Future
    from typing import Any

    from redsun.engine.actions import SRLatch
    from redsun.virtual import VirtualContainer

#: Run key giving the background scan a document cycle of its own, apart from
#: the enclosing live run.
_MEDIAN_RUN_KEY = "median_scan"
_CAPTURE_RUN_KEY = "capture"


@dataclass
class ScanAction(Action):
    """Action triggering a motor scan during live acquisition."""

    name: str = "scan"
    description: str = "Trigger a scan movement."


@dataclass
class StreamAction(Action):
    """Action toggling data streaming to a Zarr store during live acquisition."""

    name: str = "stream"
    description: str = "Toggle data streaming to disk."
    frames: int | None = 100
    togglable: bool = True
    toggle_states: tuple[str, str] = ("start", "stop")


def prepare_and_declare(
    detectors: Sequence[ReadableFlyer],
    trigger_info: TriggerInfo,
    stream_name: str,
    *,
    collect: bool = True,
    declare: bool = True,
) -> MsgGenerator[None]:
    """Prepare detectors and optionally declare their stream.

    Preparing starts live acquisition and hands each detector the sink it
    will write through; the write window opens at kickoff, so frames reach
    viewers but not storage until then. Staging is left to the caller, so
    several device groups can share one ``stage_all`` call.
    """
    for det in detectors:
        yield from bps.prepare(det, trigger_info, wait=True)
    if declare:
        yield from bps.declare_stream(*detectors, name=stream_name, collect=collect)


def teardown_acquisition(
    detectors: Sequence[ReadableFlyer],
    stream_name: str,
) -> MsgGenerator[None]:
    """Complete, collect, and unstage detectors."""
    yield from bps.complete_all(*detectors, wait=True)
    yield from bps.collect(*detectors, name=stream_name)
    yield from bps.unstage_all(*detectors)


class AcquisitionPresenter(Presenter, Loggable):
    """Presenter owning the run engine and the plans it launches.

    Parameters
    ----------
    callbacks : list[str] | None, optional
        Names of the document callbacks to subscribe on the run engine.
        ``None`` subscribes every callback the container registered; an
        empty list subscribes none.

    Attributes
    ----------
    sig_pre_launch_notify : Signal[str]
        Emitted with the plan's name before it launches.
    sig_base_dir_changed : Signal[str]
        Emitted with the new directory when a request to change where a run
        writes is accepted.
    sig_plan_done : Signal[None]
        Emitted when a non-togglable plan completes.
    sig_action_done : Signal[str]
        Emitted with the action's name when its event is cleared.
    sig_locks_changed : Signal[frozenset[str]]
        Emitted with the names of the devices a plan holds, whenever they
        change. A plan holds the devices in its arguments while it runs, and
        others with ``self.locks.hold(...)``.
    """

    sig_pre_launch_notify = Signal(str)
    sig_plan_done = Signal()
    sig_base_dir_changed = Signal(str)
    sig_action_done = Signal(str)
    sig_locks_changed = Signal(frozenset)

    def __init__(
        self,
        name: str,
        devices: Mapping[str, Device],
        /,
        callbacks: list[str] | None = None,
    ) -> None:
        super().__init__(name, devices)
        self.models = devices
        self.engine = RunEngine()
        self.deferrals = Deferrals(self.engine)

        self.futures: set[Future[Any]] = set()
        self.action_map: dict[str, SRLatch] = {}
        self.discard_by_pause = False
        self._locks = DeviceLocks()
        self._locks.sig_locks_changed.connect(self.sig_locks_changed.emit)
        # what the running plan holds for its whole run, released when it ends
        self._run_holds = ExitStack()
        # None => subscribe whatever the container registered
        self.expected_callbacks: frozenset[str] | None = (
            None if callbacks is None else frozenset(callbacks)
        )
        self.callback_tokens: dict[str, int] = {}

        self.plans: dict[str, Callable[..., MsgGenerator[Any]]] = {
            "live_stream": self.live_stream,
            "live_median_scan": self.live_median_scan,
        }
        self.plan_specs: dict[str, PlanSpec] = {}
        for plan_name, plan in self.plans.items():
            spec = self._try_build_plan_spec(plan, devices)
            if spec is not None:
                self.plan_specs[plan_name] = spec
        self._is_single_shot_plan = False

    @property
    def locks(self) -> DeviceLocks:
        """The devices the running plan holds; a plan holds more with ``hold``."""
        return self._locks

    def _try_build_plan_spec(
        self,
        plan: Callable[..., MsgGenerator[Any]],
        devices: Mapping[str, Device],
    ) -> PlanSpec | None:
        """Attempt to build a ``PlanSpec`` for *plan*; return ``None`` on failure."""
        try:
            return create_plan_spec(plan, devices)
        except UnresolvableAnnotationError as exc:
            self.logger.warning(str(exc))
            return None

    def register_providers(self, container: VirtualContainer) -> None:
        """Register plan specs and the engine's deferrals as providers."""
        container.provide(PLAN_SPECS, self.plans_specificiers())
        container.provide(DEFERRALS, self.deferrals)
        container.register_signals(self)

    def inject_dependencies(self, container: VirtualContainer) -> None:
        """Subscribe the engine to the document callbacks the session offers."""
        for name, callback in container.callbacks.items():
            if self.expected_callbacks is not None and name not in (
                self.expected_callbacks
            ):
                continue
            self.callback_tokens[name] = self.engine.subscribe(callback)
        if self.callback_tokens:
            self.logger.debug(
                f"Subscribed callbacks: {', '.join(self.callback_tokens)}"
            )
        else:
            self.logger.warning(
                "No document callbacks subscribed: live visualization and "
                "median filtering will produce nothing."
            )

    def plans_specificiers(self) -> set[PlanSpec]:
        """Return the specs of the available plans."""
        return set(self.plan_specs.values())

    @continous
    def live_median_scan(
        self,
        detectors: Sequence[ReadableFlyer],
        motor: MotorProtocol,
        step: float = 5.0,
        scan_frames: int = 40,
        stream_frames: int = 10,
        /,
        # the defaults ARE the plan's UI contract: create_plan_spec
        # introspects them to build the parameter widgets
        scan_action: Action = ScanAction(),  # noqa: B008
        stream_action: Action = StreamAction(togglable=False),  # noqa: B008
    ) -> MsgGenerator[None]:
        """Perform live data collection with temporal median filtering.

        Detectors emit frames at their live-view rate from the start. The
        "scan" action moves the motor in a square over x and y, collecting
        ``scan_frames / 4`` frames per side; the ``MedianPresenter`` callback
        computes their median when that run ends. The "stream" action flies
        the detectors to disk for ``stream_frames`` frames, as a run nested in
        this one whose start document names this run as ``parent`` and the
        last scan's run as ``median_scan``; the ``MedianPresenter`` writes
        that scan's stack into the store the capture names.

        Parameters
        ----------
        - detectors: ``Sequence[ReadableFlyer]``
            - The detectors to collect from.
        - motor: ``MotorProtocol``
            - The motor to scan with. Must expose ``x`` and ``y`` axes.
        - step: ``float``, optional
            - The motor step per frame, in the motor's units. Default is 5.0.
        - scan_frames: ``int``, optional
            - The number of frames to collect for the median. Default is 40,
            ten per side of the square.
        - stream_frames: ``int``, optional
            - The number of frames to stream to disk per stream action.
            Default is 10.

        Raises
        ------
        - ``TypeError``
            - If `motor` does not expose ``x`` and ``y`` axes.
        """
        if not {"x", "y"}.issubset(motor.axis.keys()):
            raise TypeError(
                "The provided motor must expose 'x' and 'y' MotorAxis attributes."
            )
        self.action_map.update(**scan_action.event_map, **stream_action.event_map)

        live_stream = "live_stream"
        stream_prepare_info = TriggerInfo(number_of_events=stream_frames)

        restage = True
        scan_run: str | None = None

        parent = yield from bps.open_run()

        # every live frame travels as an Event document so MedianPresenter
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

            name, event = yield from rps.wait_for_actions(
                self.action_map, wait_for="set"
            )

            if name == scan_action.name:
                scan_run = yield from self.square_scan(
                    detectors, motor, step, scan_frames // 4, parent=parent
                )

            elif name == stream_action.name:
                self.logger.debug("Start writing")
                yield from self.capture(
                    detectors, live_stream, parent=parent, median_scan=scan_run
                )
                restage = True
                self.logger.debug("Writing complete")

            self.clear_and_notify(name, event)

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

        The stack is emitted as Event documents in a nested run, so
        [`MedianPresenter`][redsun_mimir.presenter.MedianPresenter] can
        accumulate the frames and compute the median when that run stops.
        The sides are x, y, -x, -y, with *frames_per_side* frames along
        each. A frame is taken where the motor already stands and before
        every move, so the stack starts at the position the scan was asked
        from and the last move closes the square back onto it. Every frame
        goes in an event of its own, with the axis positions it was taken at;
        the event's ``seq_num`` is the frame's place in the stack, the
        ``frame_id`` those positions are written under. Returns the run's
        uid.

        Parameters
        ----------
        parent : str, optional
            The uid of the run this scan serves, recorded on its start
            document.
        """
        # TODO: handle the case of failure in motor movement or detector gracefully;
        # probably best to wrap any exception in try-except.
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
            self.logger.debug(
                f"Frame {frame}/{len(square)} taken; "
                f"moving {axis.name} by {direction} steps."
            )
            yield from bps.mvr(axis, direction)
        yield from bps.close_run()
        return uid

    @set_run_key_decorator(_CAPTURE_RUN_KEY)  # type: ignore[untyped-decorator]
    def capture(
        self,
        detectors: Sequence[ReadableFlyer],
        stream_name: str,
        *,
        parent: str,
        median_scan: str | None = None,
        until_reset: bool = False,
    ) -> MsgGenerator[str]:
        """Fly the prepared detectors to disk in a nested run and return its uid.

        The start document names *parent*, the run served, and *median_scan*,
        the scan whose stack goes into the store this capture names. With
        *until_reset* the window stays open until the action that opened it
        is toggled off. The detectors are left unstaged for the next capture.
        """
        uid: str = yield from bps.open_run(
            md={"purpose": "capture", "parent": parent, "median_scan": median_scan}
        )
        yield from bps.declare_stream(*detectors, name=stream_name, collect=True)
        yield from bps.kickoff_all(*detectors, wait=True)
        if until_reset:
            yield from rps.wait_for_actions(self.action_map, wait_for="reset")
        yield from teardown_acquisition(detectors, stream_name)
        yield from bps.close_run()
        return uid

    @continous(togglable=True)
    def live_stream(
        self,
        detectors: Sequence[ReadableFlyer],
        frames: int = 10,
        write_forever: bool = False,
        /,
        # the default IS the plan's UI contract (see live_median_scan)
        stream_action: Action = StreamAction(),  # noqa: B008
    ) -> MsgGenerator[None]:
        """Perform live data collection and optionally store data to disk.

        The `stream` action streams the acquired frames to a Zarr store for
        `frames` frames, as a run nested in this one whose start document
        names this run as ``parent``. Live visualization continues meanwhile.

        Parameters
        ----------
        - detectors: ``Sequence[ReadableFlyer]``
            - The detectors to collect from.
            - Must also implement the `Preparable` and `Flyable` protocols.
        - frames: ``int``, optional
            - The number of frames to stream to disk. Default is 10.
        - write_forever: ``bool``, optional
            - If True, stream until the `stream` action is toggled off,
            ignoring `frames`. Default is False.
        """
        stream_name = "live_stream"
        trigger_info = TriggerInfo(number_of_events=0 if write_forever else frames)

        self.action_map.update(**stream_action.event_map)

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
            name, current_action = yield from rps.wait_for_actions(
                self.action_map, wait_for="set"
            )
            self.logger.debug("Start writing")
            yield from self.capture(
                detectors, stream_name, parent=parent, until_reset=write_forever
            )
            self.logger.debug("Writing complete")
            self.clear_and_notify(name, current_action)

    @slot
    def launch_plan(self, plan_name: str, param_values: Mapping[str, Any]) -> None:
        """Launch *plan_name* with the parameter values the UI collected.

        Refused, with a warning, while another plan runs.
        """
        if self.futures:
            self.logger.warning(f"A plan is running; {plan_name!r} not launched")
            return
        # an action's latch lives on the action instance, which the plan's
        # default arguments share across launches: one left set by a stop
        # would fire the action as soon as the next launch waits on it
        for latch in self.action_map.values():
            latch.reset()
        self.action_map.clear()
        plan = self.plans[plan_name]
        spec = self.plan_specs[plan_name]

        resolved = resolve_arguments(spec, param_values, self.models)
        args, kwargs = collect_arguments(spec, resolved)

        self.sig_pre_launch_notify.emit(plan_name)
        self._run_holds.enter_context(
            self._locks.hold(*devices_in([*args, *kwargs.values()]))
        )
        fut = self.engine(plan(*args, **kwargs))
        self.futures.add(fut)
        fut.add_done_callback(self._notify_plan_done)
        fut.add_done_callback(self._release_unless_paused)
        fut.add_done_callback(self._discard_future)

    def _release_unless_paused(self, fut: Future[Any]) -> None:
        """Release what the run holds, unless its future settled for a pause.

        A paused plan resumes with a new future, and keeps its devices locked
        until that one settles.
        """
        if not self.discard_by_pause:
            self._run_holds.close()

    def _notify_plan_done(self, fut: Future[Any]) -> None:
        """Emit ``sig_plan_done`` when a plan future settles.

        The signal carries no payload, so the future is dropped.
        """
        self.sig_plan_done.emit()

    def clear_and_notify(self, name: str, event: SRLatch) -> None:
        """Reset *event* and emit ``sig_action_done`` with *name*."""
        event.reset()
        self.sig_action_done.emit(name)

    @slot
    def toggle_action_event(self, action_name: str, state: bool) -> None:
        """Set or reset the latch of *action_name*, on the engine's loop."""
        event = self.action_map[action_name]
        if state:
            self.engine.loop.call_soon_threadsafe(event.set)
        else:
            self.engine.loop.call_soon_threadsafe(event.reset)

    @slot
    def pause_or_resume_plan(self, pause: bool) -> None:
        """Pause the running plan, or resume it when *pause* is false."""
        if pause:
            self.discard_by_pause = True
            self.engine.request_pause(defer=True)
        else:
            # when resuming, the previous
            # future has beend discarded;
            # we store the new future again
            fut = self.engine.resume()
            self.futures.add(fut)
            fut.add_done_callback(self._release_unless_paused)
            fut.add_done_callback(self._discard_future)

    @slot
    def set_base_dir(self, base_dir: str) -> None:
        """Announce *base_dir* as where the devices of a run write.

        Refused while a plan runs, so the files of one run stay under one root.
        """
        if self.futures:
            self.logger.warning(
                f"A plan is running; {base_dir!r} takes effect between runs only"
            )
            return
        self.sig_base_dir_changed.emit(base_dir)

    @slot
    def stop_plan(self) -> None:
        """Stop the running plan, if any."""
        if self.engine.state == "idle":
            self.logger.debug("No plan to stop")
            return
        self.engine.stop()

    def shutdown(self) -> None:
        """Abort the running plan, if any, without emitting ``sig_plan_done``."""
        if len(self.futures) > 0:
            self.logger.debug("Aborting running plan(s) during presenter shutdown.")
            with self.sig_plan_done.blocked():
                # temporarily suppress the RequestAbort
                # exception from bluesky, as it is expected
                # during shutdown and does not indicate
                # an actual error in this context
                bluesky_log = logging.getLogger("bluesky")
                bluesky_log.addFilter(_SuppressRequestAbort())
                try:
                    self.engine.abort()
                finally:
                    bluesky_log.removeFilter(_SuppressRequestAbort())

    def _discard_future(self, fut: Future[Any]) -> None:
        # TODO: consider emitting a result
        # if the plan was not paused
        # and it also discards the future from the set
        if self.discard_by_pause:
            self.discard_by_pause = False
        self.futures.discard(fut)


def devices_in(values: Iterable[Any]) -> list[Device]:
    """Return the devices among *values*, and those one level inside a sequence or mapping."""
    found: list[Device] = []
    for value in values:
        if isinstance(value, Device):
            found.append(value)
        elif isinstance(value, Mapping):
            found.extend(v for v in value.values() if isinstance(v, Device))
        elif isinstance(value, Sequence) and not isinstance(value, str):
            found.extend(v for v in value if isinstance(v, Device))
    return found


class _SuppressRequestAbort(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not (record.exc_info and isinstance(record.exc_info[1], RequestAbort))
