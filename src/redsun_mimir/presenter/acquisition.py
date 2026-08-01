from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence  # noqa: TC003
from dataclasses import dataclass
from typing import TYPE_CHECKING

import bluesky.plan_stubs as bps
import redsun.engine.plan_stubs as rps
from bluesky.preprocessors import set_run_key_wrapper
from bluesky.utils import MsgGenerator, RequestAbort
from ophyd_async.core import TriggerInfo
from redsun.engine import RunEngine
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

from redsun_mimir.protocols import (  # noqa: TC001
    MotorProtocol,
    ReadableFlyer,
)
from redsun_mimir.providers import PLAN_SPECS
from redsun_mimir.streams import LIVE_VIEW_STREAM, MEDIAN_SCAN_STREAM

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from concurrent.futures import Future
    from typing import Any

    from ophyd_async.core import Device
    from redsun.engine.actions import SRLatch
    from redsun.virtual import VirtualContainer

#: Run key isolating the background scan from the enclosing live run, so the
#: median presenter sees a start/descriptor/event/stop cycle of its own.
_MEDIAN_RUN_KEY = "median_scan"


@dataclass
class ScanAction(Action):
    """Action to trigger a scan during live acquisition.

    This action can be used to trigger a scan movement
    of a motor during a live acquisition plan.
    """

    name: str = "scan"
    description: str = "Trigger a scan movement."


@dataclass
class StreamAction(Action):
    """Action to trigger data streaming to disk during live acquisition.

    This action can be used to trigger data streaming to a Zarr store
    on disk during a live acquisition plan.

    Attributes
    ----------
    frames : int
        The number of frames to stream to disk.
    """

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
    *will* write through; the write window itself only opens at kickoff, so
    frames reach viewers but not storage until then.

    Staging is the caller's responsibility so that multiple device
    groups can be staged together in one ``stage_all`` call.
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
    """A centralized acquisition presenter to manage a Bluesky run engine.

    Parameters
    ----------
    name : str
        Identity key of the presenter.
    devices : Mapping[str, Device]
        The available devices in the application.
    callbacks : list[str] | None, optional
        Names of the document callbacks to subscribe on the run engine.
        Defaults to ``None``, meaning **every** callback registered on the
        virtual container is subscribed - live visualization and median
        filtering are document-driven, so an unlisted callback is a silently
        dead viewer. Pass an explicit list to restrict the selection, or an
        empty list to subscribe none.

    Attributes
    ----------
    sig_pre_launch_notify : Signal[str]
        Emitted before launching a plan,
        carrying the name of the plan to be launched as a `str`.
        Useful to notify other presenters to prepare
        for the upcoming plan launch (e.g., to set up storage paths).
    sig_plan_done : Signal[None]
        Emitted when a non-togglable plan completes.
    sig_action_done : Signal[str]
        Emitted when an action event is cleared.
        Carries the name of the action as a `str`.
    """

    sig_pre_launch_notify = Signal(str)
    sig_plan_done = Signal()
    sig_action_done = Signal(str)

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

        self.futures: set[Future[Any]] = set()
        self.action_map: dict[str, SRLatch] = {}
        self.discard_by_pause = False
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
        """Register plan specs as a provider in the DI container."""
        container.provide(PLAN_SPECS, self.plans_specificiers())
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
        """Return the current set of plan specifications for the available plans."""
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

        When starting the plan, detectors will start emitting acquired frames at their live-view rates.
        If the "scan" action is triggered from the UI, the plan will perform a square motor movement
        over x and y axis, collecting ``scan_frames / 4`` frames for each side of the rectangle.
        The ``MedianPresenter`` callback accumulates these frames and computes the median at the
        end of the run.

        If the "stream" action is triggered, the plan will fly the detectors to disk for
        ``stream_frames`` frames. If a scan was previously performed, the computed median
        frame will also be written to disk.

        Parameters
        ----------
        - detectors: ``Sequence[MedianFlyer]``
            - The detectors to use for data collection.
            - They must provide a `median` attribute that is a `MedianDevice`, which computes the median of the acquired frames.
        - motor: ``XYMotor``
            - The motor to use for the scan movement.
            - Must expose ``x`` and ``y`` as
            [`MotorAxis`][redsun_mimir.device.axis.MotorAxis] attributes.
        - step: ``float``, optional
            - The step size for motor movement. Default is 5.0.
            - The measurement unit is determined by the motor in use.
        - scan_frames: ``int``, optional
            - The number of frames to collect for median filtering.
            - Default is 40 (resulting in 10 frames per side of the square).
        - stream_frames: ``int``, optional
            - The number of frames to stream to disk when the stream action is triggered.
            - Default is 10.

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

        live_stream_declared = False
        restage = True

        yield from bps.open_run()

        # every live frame travels as an Event document so MedianPresenter
        # can divide it by the background median and publish the result
        for det in detectors:
            yield from bps.monitor(det.buffer, name=LIVE_VIEW_STREAM)

        while True:
            if restage:
                yield from bps.stage_all(*detectors)
                yield from prepare_and_declare(
                    detectors,
                    stream_prepare_info,
                    live_stream,
                    declare=not live_stream_declared,
                )
                live_stream_declared = True
                restage = False

            name, event = yield from rps.wait_for_actions(
                self.action_map, wait_for="set"
            )

            if name == scan_action.name:
                yield from self.square_scan(detectors, motor, step, scan_frames // 4)

            elif name == stream_action.name:
                self.logger.debug("Start writing")
                yield from bps.kickoff_all(*detectors, wait=True)
                yield from teardown_acquisition(detectors, live_stream)
                restage = True
                self.logger.debug("Writing complete")

            self.clear_and_notify(name, event)

    def square_scan(
        self,
        detectors: Sequence[ReadableFlyer],
        motor: MotorProtocol,
        step: float,
        frames_per_side: int,
    ) -> MsgGenerator[None]:
        """Collect a background stack by moving the motor in a square.

        The stack is emitted as Event documents in a **nested run**, which
        gives [`MedianPresenter`][redsun_mimir.presenter.MedianPresenter] a
        natural boundary: it accumulates the frames and computes - and
        writes - the median when that run stops.

        Scan sequence is x -> y -> -x -> -y, with *frames_per_side* frames
        collected along each side.

        Parameters
        ----------
        detectors : Sequence[ReadableFlyer]
            The detectors to read from before each motor movement.
        motor : MotorProtocol
            The motor to use for the scan movement.
        step : float
            The step size for motor movement.
        frames_per_side : int
            The number of frames to collect for each side of the square.
        """
        yield from set_run_key_wrapper(
            self._square_scan_run(detectors, motor, step, frames_per_side),
            _MEDIAN_RUN_KEY,
        )

    def _square_scan_run(
        self,
        detectors: Sequence[ReadableFlyer],
        motor: MotorProtocol,
        step: float,
        frames_per_side: int,
    ) -> MsgGenerator[None]:
        """Emit the square-scan stack as its own run."""
        # TODO: handle the case of failure in motor movement or detector gracefully;
        # probably best to wrap any exception in try-except.
        x = motor.axis["x"]
        y = motor.axis["y"]

        yield from bps.open_run(md={"purpose": MEDIAN_SCAN_STREAM})
        for axis, direction in ((x, step), (y, step), (x, -step), (y, -step)):
            for _ in range(frames_per_side):
                self.logger.debug(f"Moving {axis.name} by {direction} steps.")
                yield from bps.create(name=MEDIAN_SCAN_STREAM)
                for det in detectors:
                    yield from bps.read(det.buffer)
                yield from bps.save()
                yield from bps.mvr(axis, direction)
                yield from bps.sleep(0.05)
        yield from bps.close_run()

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

        Provides an optional `stream` action that, when triggered from the UI,
        starts streaming the acquired data to a Zarr store on disk on the
        specified path, for a given number of `frames`.

        While streaming is active, live visualization continues as normal.

        Parameters
        ----------
        - detectors: ``Sequence[ReadableFlyer]``
            - The detectors to use for data collection.
            - Must implement the additional `Preparable` and `Flyable` protocols.
        - frames: ``int``, optional
            - The number of images to stream to disk.
            - Default is 10.
        - write_forever: ``bool``, optional
            - If True, the data will be streamed to disk until
            the `stream` action is toggled off from the UI, disregarding
            the `frames` parameter.
            Default is False (only `frames` number of images will be streamed).
        """
        streams_declared = False
        stream_name = "live_stream"
        trigger_info = TriggerInfo(number_of_events=0 if write_forever else frames)

        self.action_map.update(**stream_action.event_map)

        yield from bps.open_run()

        # live visualization travels as Event documents, so the viewer sees
        # frames through the same document sequence as everything else
        for det in detectors:
            yield from bps.monitor(det.buffer, name=LIVE_VIEW_STREAM)

        while True:
            yield from bps.stage_all(*detectors)
            yield from prepare_and_declare(
                detectors,
                trigger_info,
                stream_name,
                declare=not streams_declared,
            )
            streams_declared = True
            name, current_action = yield from rps.wait_for_actions(
                self.action_map, wait_for="set"
            )
            self.logger.debug("Start writing")
            # kickoff opens the write window: frames were already reaching
            # viewers from prepare onwards, they now also reach storage
            yield from bps.kickoff_all(*detectors, wait=True)
            if write_forever:
                name, current_action = yield from rps.wait_for_actions(
                    self.action_map, wait_for="reset"
                )
            yield from teardown_acquisition(detectors, stream_name)
            self.logger.debug("Writing complete")
            self.clear_and_notify(name, current_action)

    @slot
    def launch_plan(self, plan_name: str, param_values: Mapping[str, Any]) -> None:
        """Launch the specified plan.

        Parameters
        ----------
        plan_name : ``str``
            The name of the plan to launch.
        param_values : ``Mapping[str, Any]``
            The parameter values to pass to the plan.
            Elaborated from the UI inputs.
        """
        self.action_map.clear()
        plan = self.plans[plan_name]
        spec = self.plan_specs[plan_name]

        resolved = resolve_arguments(spec, param_values, self.models)
        args, kwargs = collect_arguments(spec, resolved)

        self.sig_pre_launch_notify.emit(plan_name)
        fut = self.engine(plan(*args, **kwargs))
        self.futures.add(fut)

        if not spec.togglable:
            fut.add_done_callback(self._notify_plan_done)

        fut.add_done_callback(self._discard_future)

    def _notify_plan_done(self, fut: Future[Any]) -> None:
        """Emit ``sig_plan_done`` when a non-togglable plan future settles.

        ``Future.add_done_callback`` passes the future to its callback,
        while ``sig_plan_done`` carries no payload; the future is discarded
        here rather than handed to the signal.
        """
        self.sig_plan_done.emit()

    def clear_and_notify(self, name: str, event: SRLatch) -> None:
        """Reset the given latch and emit "action done" signal.

        Parameters
        ----------
        name : ``str``
            The name of the action.
        event : ``SRLatch``
            The latch to reset and notify.
        """
        event.reset()
        self.sig_action_done.emit(name)

    @slot
    def toggle_action_event(self, action_name: str, state: bool) -> None:
        """Toggle the event associated with the given action name."""
        event = self.action_map[action_name]
        if state:
            self.engine.loop.call_soon_threadsafe(event.set)
        else:
            self.engine.loop.call_soon_threadsafe(event.reset)

    @slot
    def pause_or_resume_plan(self, pause: bool) -> None:
        """Pause or resume the running plan.

        Parameters
        ----------
        pause : ``bool``
            If True, pause the plan; if False, resume the plan.
        """
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
        """Stop the running plan."""
        self.engine.stop()

    def shutdown(self) -> None:
        """Shutdown the presenter.

        If there is a running plan, abort it.
        """
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
