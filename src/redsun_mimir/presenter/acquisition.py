from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence  # noqa: TC003
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

import bluesky.plan_stubs as bps
import redsun.engine.plan_stubs as rps
from bluesky.utils import MsgGenerator, RequestAbort  # noqa: TC002
from dependency_injector import providers
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
from redsun.storage import PrepareInfo
from redsun.utils import find_signals
from redsun.virtual import Signal

from redsun_mimir.device.axis import MotorAxis  # noqa: TC001
from redsun_mimir.protocols import (  # noqa: TC001
    DetectorProtocol,
    ReadableFlyer,
)


class XYMotor(Protocol):
    """Narrow protocol for plans that require an XY motor.

    Any device exposing ``x`` and ``y`` attributes of type
    [`MotorAxis`][redsun_mimir.device.axis.MotorAxis] satisfies this
    protocol structurally, without needing to subclass it.

    Using this protocol as a plan parameter type lets mypy verify at
    type-check time that the supplied device exposes both axes, without
    relying on runtime ``children()`` introspection.
    """

    x: MotorAxis
    y: MotorAxis


if TYPE_CHECKING:
    from concurrent.futures import Future
    from typing import Any, Callable, Mapping

    from redsun.device import Device
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
    detectors: Sequence[DetectorProtocol],
    motor: XYMotor,
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
    for idx in range(2):
        axis_device = getattr(motor, axis[idx])
        for _ in range(frames_per_side):
            yield from bps.trigger_and_read(detectors, "square_scan")
            yield from bps.mvr(axis_device, step)
            yield from bps.sleep(0.05)
    # scan on the negative direction
    for idx in range(2):
        axis_device = getattr(motor, axis[1 - idx])
        for _ in range(frames_per_side):
            yield from bps.trigger_and_read(detectors, "square_scan")
            yield from bps.mvr(axis_device, -step)
            yield from bps.sleep(0.05)


# TODO: move this somewhere else
def convert_to_target_egu(
    step: float,
    from_egu: str,
    to_egu: str,
) -> tuple[float, float]:
    """Convert step value from one engineering unit to another.

    Parameters
    ----------
    step: ``float``
        The step value to convert.
    from_egu: ``str``
        The source unit (e.g., "μm", "mm", "nm").
    to_egu: ``str``
        The target unit (e.g., "μm", "mm", "nm").

    Returns
    -------
    ``tuple[float, float]``
        A tuple with two values, in the following order:
        - The original step value in the source engineering unit.
        - The converted step value in the target engineering unit.
    """
    old_step = step
    if from_egu == to_egu:
        return old_step, step

    to_meters = {
        "nm": 1e-9,
        "um": 1e-6,
        "mm": 1e-3,
    }

    # convert to meters first, then to target egu
    new_step = step * to_meters[from_egu] / to_meters[to_egu]

    return old_step, new_step


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
            "live_count": self.live_count,
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

    @continous(togglable=True, pausable=True)
    def live_count(
        self,
        detectors: Sequence[DetectorProtocol],
    ) -> MsgGenerator[None]:
        """Start a live acquisition with the selected detectors.

        To pause or resume the live acquisition, toggle the "Pause/Resume" button.
        To stop the live acquisition, click the "Stop" button.

        Parameters
        ----------
        - detectors : ``Sequence[DetectorProtocol]``
            - The detectors to use in the live acquisition.
        """
        yield from bps.open_run()
        yield from bps.stage_all(*detectors)

        while True:
            # keep a checkpoint in case of pause/resume
            yield from bps.checkpoint()
            yield from bps.trigger_and_read(detectors, name="live_count")

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

        yield from bps.open_run()
        yield from bps.stage_all(*detectors)
        for _ in range(frames):
            yield from bps.trigger_and_read(detectors, name="snap")
        yield from bps.unstage_all(*detectors)
        yield from bps.close_run(exit_status="success")

    @continous
    def live_median_scan(
        self,
        detectors: Sequence[ReadableFlyer],
        motor: XYMotor,
        step: float = 1.0,
        step_egu: Literal["um", "mm", "nm"] = "um",
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
        - step_egu: ``Literal["um", "mm", "nm"]``, optional
            - The engineering unit for the step size.
            - Default is "um".
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
        if not (hasattr(motor, "x") and hasattr(motor, "y")):
            raise TypeError(
                "The provided motor must expose 'x' and 'y' MotorAxis attributes."
            )

        axis = ("x", "y") if direction == "xy" else ("y", "x")
        self.event_map.update(**scan.event_map, **stream.event_map)

        # Resolve motor EGU from the x-axis step_size descriptor
        _step_desc = motor.x.step_size.describe()
        motor_egu: str = next(iter(_step_desc.values())).get("units") or "um"

        old_step, step = convert_to_target_egu(
            step, from_egu=step_egu, to_egu=motor_egu
        )

        live_stream = "live"
        stream_name = "stream"
        stream_declared = False

        yield from bps.open_run()
        yield from bps.stage_all(*detectors)

        prepare_info = PrepareInfo(number_of_events=stream_frames, write_forever=False)
        yield from bps.prepare(motor, prepare_info, wait=True)
        for det in detectors:
            yield from bps.prepare(det, prepare_info, wait=True)

        while True:
            name, event = yield from rps.read_while_waiting(
                detectors,
                self.event_map,
                live_stream,
            )
            if name == scan.name:
                if motor_egu != step_egu:
                    motor.x.step_size.set(step)
                    motor.y.step_size.set(step)
                yield from square_scan(
                    detectors,  # type: ignore[arg-type]
                    motor,
                    step,
                    scan_frames // 4,
                    axis,
                )
                if step != old_step:
                    motor.x.step_size.set(old_step)
                    motor.y.step_size.set(old_step)

            elif name == stream.name:
                self.logger.debug("Starting data streaming to disk")

                if not stream_declared:
                    yield from bps.declare_stream(
                        *detectors, name=stream_name, collect=True
                    )
                    stream_declared = True
                yield from bps.kickoff_all(*detectors)

                yield from bps.complete_all(*detectors, wait=True)
                self.logger.debug("Flight complete.")

                yield from bps.collect(*detectors, name=stream_name)
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
        live_stream = "live"
        stream_name = "stream"
        stream_declared = False

        self.event_map.update(action.event_map)

        yield from bps.open_run()
        yield from bps.stage_all(*detectors)
        while True:
            # live acquisition; wait for stream action
            name, event = yield from rps.read_while_waiting(
                detectors, self.event_map, stream_name=live_stream, wait_for="set"
            )
            self.logger.debug("Starting data streaming to disk")

            prepare_info = PrepareInfo(
                number_of_events=frames, write_forever=write_forever
            )
            for detector in detectors:
                yield from bps.prepare(detector, prepare_info, wait=True)

            if not stream_declared:
                yield from bps.declare_stream(
                    *detectors, name=stream_name, collect=True
                )
            yield from bps.kickoff_all(*detectors, wait=True)
            if write_forever:
                self.logger.debug("Writing forever.")
                name, event = yield from rps.read_while_waiting(
                    detectors, self.event_map, stream_name=live_stream, wait_for="reset"
                )
                self.logger.debug("Done. Stopping streaming.")
            yield from bps.complete_all(*detectors, wait=True)
            self.logger.debug("Flight complete.")

            yield from bps.collect(*detectors, name=stream_name)

            stream_declared = True
            self.clear_and_notify(name, event)
            self.logger.debug("Finished data streaming to disk.")

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
