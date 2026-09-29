from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence  # noqa: TC003
from typing import TYPE_CHECKING, Any

import bluesky.plan_stubs as bps
import redsun.engine.plan_stubs as rps
from bluesky.preprocessors import set_run_key_decorator
from bluesky.utils import MsgGenerator, RequestAbort
from ophyd_async.core import TriggerInfo
from psygnal import Signal
from redsun import CallbackType, DeviceMapping, HasPlans, slot
from redsun.engine import Deferrals, RunEngine
from redsun.engine.actions import ActionManager, PlanAction, continuous
from redsun.log import Loggable
from redsun.presenter.plan_spec import (
    PlanSpec,
    UnresolvableAnnotationError,
    collect_arguments,
    create_plan_spec,
    resolve_arguments,
)

from redsun_mimir.common import LIVE_VIEW_STREAM
from redsun_mimir.protocols import HasActions, ReadableFlyer

if TYPE_CHECKING:
    from concurrent.futures import Future

    from redsun import PlanEntry

#: Run key giving a capture a document cycle of its own, apart from the
#: enclosing live run.
_CAPTURE_RUN_KEY = "capture"

#: The action of `live_stream` writing frames to disk.
STREAM = PlanAction(
    name="stream",
    description="Toggle data streaming to disk.",
    toggle_states=("start", "stop"),
)


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
    several device groups can share one `stage_all` call.
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


@set_run_key_decorator(_CAPTURE_RUN_KEY)  # type: ignore[untyped-decorator]
def capture(
    detectors: Sequence[ReadableFlyer],
    stream_name: str,
    *,
    parent: str,
    median_scan: str | None = None,
    until: MsgGenerator[None] | None = None,
) -> MsgGenerator[str]:
    """Fly the prepared detectors to disk in a nested run and return its uid.

    The start document names *parent*, the run served, and *median_scan*,
    the scan whose stack goes into the store this capture names. With
    *until* the window stays open until that plan returns. The detectors are
    left unstaged for the next capture.
    """
    uid: str = yield from bps.open_run(
        md={"purpose": "capture", "parent": parent, "median_scan": median_scan}
    )
    yield from bps.declare_stream(*detectors, name=stream_name, collect=True)
    yield from bps.kickoff_all(*detectors, wait=True)
    if until is not None:
        yield from until
    yield from teardown_acquisition(detectors, stream_name)
    yield from bps.close_run()
    return uid


class AcquisitionPresenter(Loggable):
    """Presenter owning the run engine and running every plan of the session.

    It offers `live_stream` itself, and runs the plans of every component
    with a `plan_map`. A run gets the document callbacks its plan lists,
    then the ones the user attached to it; no callback follows the engine
    between runs.
    """

    sig_pre_launch_notify = Signal(str)
    """Emitted with the plan's name before it launches."""

    sig_plan_done = Signal()
    """Emitted when a plan ends, however it ends."""

    sig_locks_changed = Signal(frozenset)
    """Emitted with the names of the devices a plan holds, whenever they
    change. A scan locks its motor and detectors, a capture its detectors."""

    def __init__(self, name: str, *, devices: DeviceMapping) -> None:
        self.name = name
        self.devices = devices
        self.engine = RunEngine()
        self.actions = ActionManager()
        self._deferrals = Deferrals(self.engine)

        self.futures: set[Future[Any]] = set()
        self.discard_by_pause = False
        self.engine.sig_locks_changed.connect(self.sig_locks_changed.emit)

        self.plans: dict[str, PlanEntry] = {}
        self.plan_specs: dict[str, PlanSpec] = {}
        self.callbacks: dict[str, CallbackType] = {}
        self._action_owners: dict[str, HasActions] = {}
        self._running: str | None = None

    def plan_deferrals(self) -> Deferrals:
        """Return the deferrals of this presenter's engine."""
        return self._deferrals

    def plan_map(self) -> Mapping[str, PlanEntry]:
        """Return the plan this presenter offers."""
        return {"live_stream": {"plan": self.live_stream}}

    def setup(
        self,
        providers: Mapping[str, HasPlans],
        callbacks: Mapping[str, CallbackType],
    ) -> None:
        """Collect the plans of every component offering them, and the callbacks.

        A plan whose signature no plan widget can show is logged and left out.
        The actions of a plan are those of the component offering it, when
        that component holds any.
        """
        for component in providers.values():
            for plan_name, entry in component.plan_map().items():
                try:
                    self.plan_specs[plan_name] = create_plan_spec(
                        entry["plan"], self.devices
                    )
                except (UnresolvableAnnotationError, ValueError) as error:
                    self.logger.warning(str(error))
                    continue
                self.plans[plan_name] = entry
                if isinstance(component, HasActions):
                    self._action_owners[plan_name] = component
        self.callbacks = dict(callbacks)

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
                self.logger.debug("Start writing")
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
                self.logger.debug("Writing complete")
            finally:
                self.actions.done(name)

    @slot
    def launch_plan(
        self,
        plan_name: str,
        param_values: Mapping[str, Any],
        attached: Sequence[str] = (),
    ) -> None:
        """Launch *plan_name* with the parameter values the UI collected.

        The run gets the callbacks its plan lists, then those named in
        *attached*, for this run only. Refused, with a warning, while another
        plan runs.
        """
        if self.futures:
            self.logger.warning(f"A plan is running; {plan_name!r} not launched")
            return
        entry = self.plans[plan_name]
        spec = self.plan_specs[plan_name]

        resolved = resolve_arguments(spec, param_values, self.devices)
        args, kwargs = collect_arguments(spec, resolved)
        # a DocumentRouter is callable as (name, doc), but not typed as bluesky asks
        subs: list[Any] = [
            *entry.get("callbacks", ()),
            *(self.callbacks[n] for n in attached),
        ]

        self.sig_pre_launch_notify.emit(plan_name)
        self._running = plan_name
        fut = self.engine(entry["plan"](*args, **kwargs), subs)
        self.futures.add(fut)
        fut.add_done_callback(self._notify_plan_done)
        fut.add_done_callback(self._discard_future)

    @slot
    def request_action(self, name: str, on: bool) -> None:
        """Ask for the action *name* of the last plan launched, or ask it to end.

        The request goes to the actions of the component offering that plan;
        with no such component it is logged and dropped.
        """
        owner = self._action_owners.get(self._running or "")
        if owner is None:
            self.logger.warning(f"Action {name!r} refused: no plan holds actions")
            return
        owner.actions.request(name, on)

    def _notify_plan_done(self, fut: Future[Any]) -> None:
        """Emit `sig_plan_done` when a plan future settles.

        The signal carries no payload, so the future is dropped.
        """
        self.sig_plan_done.emit()

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
            fut.add_done_callback(self._discard_future)

    @slot
    def stop_plan(self) -> None:
        """Stop the running plan, if any."""
        if self.engine.state == "idle":
            self.logger.debug("No plan to stop")
            return
        self.engine.stop()

    def shutdown(self) -> None:
        """Abort the running plan, if any, without emitting `sig_plan_done`."""
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


class _SuppressRequestAbort(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not (record.exc_info and isinstance(record.exc_info[1], RequestAbort))
