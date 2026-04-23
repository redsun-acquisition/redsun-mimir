from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence  # noqa: TC003
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import bluesky.plan_stubs as bps
import redsun.engine.plan_stubs as rps
from bluesky.utils import MsgGenerator, RequestAbort  # noqa: TC002
from dependency_injector import providers
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
from redsun.utils import find_signals
from redsun.virtual import Signal

from redsun_mimir.protocols import (  # noqa: TC001
    DetectorProtocol,
    MotorProtocol,
    ReadableFlyer,
)

if TYPE_CHECKING:
    from concurrent.futures import Future
    from typing import Any, Callable, Mapping

    from ophyd_async.core import Device
    from redsun.engine.actions import SRLatch
    from redsun.virtual import VirtualContainer


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


def square_scan(
    detectors: Sequence[ReadableFlyer],
    motor: MotorProtocol,
    step: float,
    frames_per_side: int,
    axis: tuple[str, str],
) -> MsgGenerator[None]:
    """Perform a square scan movement with the specified motor and detectors.

    Performs a square scan by moving the motor in a square pattern; before
    each movement step, a reading is taken from the specified detectors.

    Parameters
    ----------
    detectors : ``Sequence[DetectorProtocol]``
        The detectors to use for data collection.
    motor : ``XYMotor``
        The motor to use for the scan movement. Must expose ``x`` and ``y``
        axes as [`MotorAxis`][redsun_mimir.device.axis.MotorAxis] attributes.
    step : ``float``
        The step size for motor movement.
    frames_per_side : ``int``
        The number of frames to collect for each side of the square.
    axis : ``tuple[str, str]``
        The order of motor movement axes (e.g. ``("x", "y")``).

    Yields
    ------
    ``MsgGenerator[None]``
        A generator yielding Bluesky messages for the square scan.
    """
    # scan on the positive direction...
    buffers = [det.buffer for det in detectors]
    for idx in range(2):
        axis_device = motor.axis[axis[idx]]
        for _ in range(frames_per_side):
            yield from bps.trigger_and_read(buffers, "square_scan")
            yield from bps.mvr(axis_device, step)
            yield from bps.sleep(0.05)
    # scan on the negative direction
    for idx in range(2):
        axis_device = motor.axis[axis[1 - idx]]
        for _ in range(frames_per_side):
            yield from bps.trigger_and_read(buffers, "square_scan")
            yield from bps.mvr(axis_device, -step)
            yield from bps.sleep(0.05)


class AcquisitionPresenter(Presenter, Loggable):
    """A centralized acquisition presenter to manage a Bluesky run engine.

    Parameters
    ----------
    devices: Mapping[str, Device]
        The available devices in the application.
        The virtual bus to register signals on.
    callbacks: list[str] | None, keyword-only, optional
        Callback names to subscribe to on the run engine, if any.
        If not provided, no callbacks will be subscribed to.
        Defaults to None.

    Attributes
    ----------
    sigPreLaunchNotify : Signal[str]
        Emitted before launching a plan,
        carrying the name of the plan to be launched as a `str`.
        Useful to notify other presenters to prepare
        for the upcoming plan launch (e.g., to set up writers).
    sigPlanDone : Signal[None]
        Emitted when a non-togglable plan completes.
    sigActionDone : Signal[str]
        Emitted when an action event is cleared.
        Carries the name of the action as a `str`.
    """

    sigPreLaunchNotify = Signal(str)
    sigPlanDone = Signal()
    sigActionDone = Signal(str)

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
        self.event_map: dict[str, SRLatch] = {}
        self.discard_by_pause = False
        self.expected_callbacks = frozenset(callbacks or [])
        self.callback_tokens: dict[str, int] = {}

        self.plans: dict[str, Callable[..., MsgGenerator[Any]]] = {
            "snap": self.snap,
            "live_stream": self.live_stream,
            "live_median_scan": self.live_median_scan,
        }
        self.plan_specs: dict[str, PlanSpec] = {}
        for name, plan in self.plans.items():
            spec = self._try_build_plan_spec(plan, devices)
            if spec is not None:
                self.plan_specs[name] = spec
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
        container.plan_specs = providers.Object(self.plans_specificiers())
        container.register_signals(self)

    def inject_dependencies(self, container: VirtualContainer) -> None:
        """Connect to the virtual container signals."""
        self._container = container

        sigs = find_signals(
            container,
            [
                "sigLaunchPlanRequest",
                "sigStopPlanRequest",
                "sigPauseResumeRequest",
                "sigActionRequest",
            ],
        )
        if "sigLaunchPlanRequest" in sigs:
            sigs["sigLaunchPlanRequest"].connect(self.launch_plan)
        if "sigStopPlanRequest" in sigs:
            sigs["sigStopPlanRequest"].connect(self.stop_plan)
        if "sigPauseResumeRequest" in sigs:
            sigs["sigPauseResumeRequest"].connect(self.pause_or_resume_plan)
        if "sigActionRequest" in sigs:
            sigs["sigActionRequest"].connect(self.toggle_action_event)

        if len(self.expected_callbacks) > 0:
            msg = ", ".join(self.expected_callbacks)
            self.logger.debug(f"Registering callbacks: {msg}")
            for name, callback in container.callbacks.items():
                if name in self.expected_callbacks:
                    token = self.engine.subscribe(callback)
                    self.callback_tokens[name] = token

    def plans_specificiers(self) -> set[PlanSpec]:
        """Return the current set of plan specifications for the available plans."""
        return set(self.plan_specs.values())

    def snap(
        self, detectors: Sequence[DetectorProtocol], frames: int = 1
    ) -> MsgGenerator[None]:
        """Take ``frames`` number snapshot from each detector.

        Parameters
        ----------
        - detectors: ``Sequence[DetectorProtocol]``
            - The detectors to take a snapshot from.
        - frames: ``int``, optional
            - The number of snapshots to take for each detector.
            Must be a non-zero, positive integer.
            Default is 1.
        """
        if frames <= 0:
            # safeguard against invalid input
            frames = 1

        prepare_info = TriggerInfo(number_of_events=frames)

        yield from bps.open_run()
        yield from bps.stage_all(*detectors)
        for detector in detectors:
            yield from bps.prepare(detector, prepare_info, wait=True)
        yield from bps.kickoff_all(*detectors, wait=True)
        yield from bps.complete_all(*detectors, wait=True)
        yield from bps.unstage_all(*detectors)
        yield from bps.close_run(exit_status="success")

    @continous
    def live_median_scan(
        self,
        detectors: Sequence[ReadableFlyer],
        motor: MotorProtocol,
        step: float = 1.0,
        scan_frames: int = 20,
        direction: Literal["xy", "yx"] = "xy",
        stream_frames: int = 10,
        /,
        scan: Action = ScanAction(),
        stream: Action = StreamAction(togglable=False),
    ) -> MsgGenerator[None]:
        """Perform live data collection with median filtering.

        When starting the plan, detectors will start emitting acquired frames at their live-view rates.
        If the "scan" action is triggered from the UI, the plan will perform a square motor movement
        over x and y axis, collecting ``scan_frames / 4`` frames for each side of the rectangle.
        The ``MedianPresenter`` callback accumulates these frames and computes the median at the
        end of the run.

        If the "stream" action is triggered, the plan will fly the detectors to disk for
        ``stream_frames`` frames.

        Parameters
        ----------
        - detectors: ``Sequence[ReadableFlyer]``
            - The detectors to use for data collection.
        - motor: ``XYMotor``
            - The motor to use for the scan movement.
            - Must expose ``x`` and ``y`` as
              [`MotorAxis`][redsun_mimir.device.axis.MotorAxis] attributes.
        - step: ``float``, optional
            - The step size for motor movement. Default is 1.0.
            - The measurement unit is determined by the motor in use.
        - scan_frames: ``int``, optional
            - The number of frames to collect for median filtering.
            - Default is 20 (resulting in 4 frames per side of the square).
        - direction: ``Literal["xy", "yx"]``, optional
            - The order of motor movement axes.
            - Default is "xy".
        - stream_frames: ``int``, optional
            - The number of frames to stream to disk when the stream action is triggered.
            - Default is 10.

        Raises
        ------
        - ``TypeError``
            - If `motor` does not expose ``x`` and ``y`` axes.
        """
        if ["x", "y"] != list(motor.axis.keys()):
            self.logger.error(
                "Motor does not have the required 'x' and 'y' axes. "
                f"Found axes: {list(motor.axis.keys())}"
            )
            raise TypeError(
                "The provided motor must expose 'x' and 'y' MotorAxis attributes."
            )
        axis = ("x", "y") if direction == "xy" else ("y", "x")
        self.event_map.update(**scan.event_map, **stream.event_map)
        stream_declared = False

        yield from bps.open_run()
        yield from bps.stage_all(*detectors)

        prepare_info = TriggerInfo(number_of_events=stream_frames)
        yield from bps.prepare(motor, prepare_info, wait=True)
        for det in detectors:
            yield from bps.prepare(det, prepare_info, wait=True)

        while True:
            name, event = yield from rps.wait_for_actions(
                self.event_map, wait_for="set"
            )
            if name == scan.name:
                yield from square_scan(
                    detectors,
                    motor,
                    step,
                    scan_frames // 4,
                    axis,
                )

            elif name == stream.name:
                self.logger.debug("Starting data streaming to disk")

                if not stream_declared:
                    yield from bps.declare_stream(*detectors, collect=True)
                    stream_declared = True
                yield from bps.kickoff_all(*detectors)
                yield from bps.complete_all(*detectors, wait=True)
                yield from bps.collect(*detectors)
                self.logger.debug("Flight complete.")

                yield from bps.collect(*detectors)
            self.clear_and_notify(name, event)

    @continous(togglable=True)
    def live_stream(
        self,
        detectors: Sequence[ReadableFlyer],
        frames: int = 10,
        write_forever: bool = False,
        /,
        action: Action = StreamAction(),
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
        stream_name = "live_stream"
        streams_declared = False
        self.event_map.update(action.event_map)
        write_info = TriggerInfo(number_of_events=0 if write_forever else frames)

        yield from bps.open_run()
        while True:
            yield from bps.stage_all(*detectors)

            for det in detectors:
                yield from bps.prepare(det, write_info, wait=True)
            if not streams_declared:
                # for the first time, declare the stream
                yield from bps.declare_stream(*detectors, name=stream_name)
                streams_declared = True
            yield from bps.kickoff_all(*detectors, wait=True)

            # live view
            name, event = yield from rps.wait_for_actions(
                self.event_map, wait_for="set"
            )

            self.logger.debug("Start writing")
            # flip write_sig — pump starts writing from next frame
            for det in detectors:
                yield from bps.abs_set(det.write_sig, True, wait=True)

            yield from bps.complete_all(*detectors, wait=True)
            yield from bps.collect(*detectors)
            yield from bps.unstage_all(*detectors)
            self.logger.debug("Writing complete")
            self.clear_and_notify(name, event)

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
        plan = self.plans[plan_name]
        spec = self.plan_specs[plan_name]

        resolved = resolve_arguments(spec, param_values, self.models)
        args, kwargs = collect_arguments(spec, resolved)

        self.sigPreLaunchNotify.emit(plan_name)
        fut = self.engine(plan(*args, **kwargs))
        self.futures.add(fut)

        if not spec.togglable:
            fut.add_done_callback(self.sigPlanDone)

        fut.add_done_callback(self._discard_future)

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
        self.sigActionDone.emit(name)

    def toggle_action_event(self, action_name: str, state: bool) -> None:
        """Toggle the event associated with the given action name."""
        event = self.event_map[action_name]
        if state:
            self.engine.loop.call_soon_threadsafe(event.set)
        else:
            self.engine.loop.call_soon_threadsafe(event.reset)

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

    def stop_plan(self) -> None:
        """Stop the running plan."""
        self.engine.stop()

    def shutdown(self) -> None:
        """Shutdown the presenter.

        If there is a running plan, abort it.
        """
        if len(self.futures) > 0:
            self.logger.debug("Aborting running plan(s) during presenter shutdown.")
            with self.sigPlanDone.blocked():
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
        if record.exc_info and isinstance(record.exc_info[1], RequestAbort):
            return False
        return True
