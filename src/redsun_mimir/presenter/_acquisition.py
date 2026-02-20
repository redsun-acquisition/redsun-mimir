from __future__ import annotations

import pathlib  # noqa: TC003
from collections.abc import Mapping, Sequence  # noqa: TC003
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal

import bluesky.plan_stubs as bps
from bluesky.utils import MsgGenerator  # noqa: TC002
from dependency_injector import providers
from sunflare.engine import RunEngine
from sunflare.log import Loggable
from sunflare.presenter import Presenter
from sunflare.virtual import IsInjectable, IsProvider, Signal

import redsun_mimir.commands as cmds
import redsun_mimir.plan_stubs as rps
from redsun_mimir.actions import Action, continous
from redsun_mimir.common import (
    PlanSpec,
    collect_arguments,
    create_plan_spec,
    resolve_arguments,
)
from redsun_mimir.device.pseudo import MedianPseudoDevice
from redsun_mimir.protocols import (  # noqa: TC001
    DetectorProtocol,
    MotorProtocol,
    ReadableFlyer,
)
from redsun_mimir.utils import find_signals

if TYPE_CHECKING:
    from concurrent.futures import Future
    from typing import Any, Callable, Mapping

    from bluesky.protocols import Readable
    from sunflare.device import Device
    from sunflare.virtual import VirtualContainer

    from redsun_mimir.actions import SRLatch


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
    motor : ``MotorProtocol``
        The motor to use for the scan movement.
    step : ``float``
        The step size for motor movement.
    frames_per_side : ``int``
        The number of frames to collect for each side of the square.
    axis : ``tuple[str, str]``
        The order of motor movement axes.

    Yields
    ------
    ``MsgGenerator[None]``
        A generator yielding Bluesky messages for the square scan.
    """
    # scan on the positive direction...
    for idx in range(2):
        ax = axis[idx]
        # set the axis direction
        yield from rps.set_property(motor, ax, propr="axis")
        for _ in range(frames_per_side):
            yield from bps.trigger_and_read(detectors, "square_scan")
            yield from bps.mvr(motor, step)
    # scan on the negative direction
    for idx in range(2):
        ax = axis[1 - idx]
        # set the axis direction
        yield from rps.set_property(motor, ax, propr="axis")
        for _ in range(frames_per_side):
            yield from bps.trigger_and_read(detectors, "square_scan")
            yield from bps.mvr(motor, -step)


def scan_and_stash(
    detectors: Sequence[ReadableFlyer],
    motor: MotorProtocol,
    cache: Sequence[MedianPseudoDevice],
    step: float,
    frames_per_side: int,
    axis: tuple[str, str],
) -> MsgGenerator[None]:
    """Perform a square scan movement with the specified motor and detectors.

    Performs a square scan by moving the motor in a square pattern; before
    each movement step, a reading is taken from the specified detectors
    and stashed into the cache model.

    Parameters
    ----------
    detectors : ``Sequence[DetectorProtocol]``
        The detectors to use for data collection.
    motor : ``MotorProtocol``
        The motor to use for the scan movement.
    cache : ``MedianPseudoDevice``
        The cache model to stash readings into.
    step : ``float``
        The step size for motor movement.
    frames_per_side : ``int``
        The number of frames to collect for each side of the square.
    axis : ``tuple[str, str]``
        The order of motor movement axes.

    Yields
    ------
    ``MsgGenerator[None]``
        A generator yielding Bluesky messages for the square scan.
    """
    # scan on the positive direction
    for idx in range(2):
        ax = axis[idx]
        # set the axis direction
        yield from rps.set_property(motor, ax, propr="axis")
        for _ in range(frames_per_side):
            yield from rps.read_and_stash(
                detectors, cache, group="stash", stream="square_scan", wait=True
            )
            yield from bps.mvr(motor, step)
    # scan on the negative direction
    for idx in range(2):
        ax = axis[1 - idx]
        # set the axis direction
        yield from rps.set_property(motor, ax, propr="axis")
        for _ in range(frames_per_side):
            yield from rps.read_and_stash(
                detectors, cache, group="stash", stream="square_scan", wait=True
            )
            yield from bps.mvr(motor, -step)


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


class AcquisitionPresenter(Presenter, IsProvider, IsInjectable, Loggable):
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
    sigPlanDone :
        Emitted when a non-togglable plan completes.
    sigActionDone :
        Emitted when an action event is cleared.
        Carries the name of the action as a `str`.
    """

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

        for command in [cmds.wait_for_actions, cmds.stash, cmds.clear_cache]:
            cmds.register_bound_command(self.engine, command)

        self.futures: set[Future[Any]] = set()
        self.event_map: dict[str, SRLatch] = {}
        self.discard_by_pause = False
        self.expected_callbacks = frozenset(callbacks or [])
        self.callback_tokens: dict[str, int] = {}

        self.plans: dict[str, Callable[..., MsgGenerator[Any]]] = {
            "snap": self.snap,
            "live_count": self.live_count,
            "live_stream": self.live_stream,
            "live_square_scan": self.live_square_scan,
            "live_median_scan": self.live_median_scan,
        }
        self.plan_specs: dict[str, PlanSpec] = {
            name: create_plan_spec(plan, devices) for name, plan in self.plans.items()
        }

    def register_providers(self, container: VirtualContainer) -> None:
        """Register plan specs as a provider in the DI container."""
        container.plan_specs = providers.Object(self.plans_specificiers())
        container.register_signals(self)

    def inject_dependencies(self, container: VirtualContainer) -> None:
        """Connect to the virtual container signals."""
        sigs = find_signals(container, [
            "sigLaunchPlanRequest",
            "sigStopPlanRequest",
            "sigPauseResumeRequest",
            "sigActionRequest",
        ])
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

    @continous(togglable=True)
    def live_square_scan(
        self,
        detectors: Sequence[DetectorProtocol],
        motor: MotorProtocol,
        step: float = 1.0,
        step_egu: Literal["um", "mm", "nm"] = "um",
        frames: int = 20,
        direction: Literal["xy", "yx"] = "xy",
        /,
        action: Action = ScanAction(),
    ) -> MsgGenerator[None]:
        """Perform live data collection with optional, triggerable square scan movement.

        When starting the plan, detectors will start emitting acquired frames at their live-view rates.
        If the "scan" action is triggered from the UI, the plan will perform a square motor movement
        over x and y axis, collecting `frames / 4` frames for each of the sides of the rectangle. For each
        movement step, a frame is collected from each detector. After completing the square scan,
        the plan will resume live acquisition.

        Parameters
        ----------
        - detectors: ``Sequence[DetectorProtocol]``
            - The detectors to use for data collection.
        - motor: ``MotorProtocol``
            - The motor to use for the scan movement.
            - It must provide two axes of movement ("X" and "Y").
        - step: ``float``, optional
            The step size for motor movement. Default is 1.0.
        - step_egu: ``Literal["um", "mm", "nm"]``, optional
            - The engineering unit for the step size.
            - Default is "um".
        - frames: ``int``, optional
            - The number of frames to collect for median filtering.
            - The rectangular movement will be divided into four sides,
            each side collecting `frames / 4` frames, one frame per motor step.
            - Default is 20 (resulting in 4 frames per side).
        - direction: ``Literal["xy", "yx"]``, optional
            - The order of motor movement.
            - `xy`: move along X axis first, then Y axis.
            - `yx`: move along Y axis first, then X axis.

        Raises
        ------
        - ``TypeError``
            - If `motor` does not provide both "X" and "Y" axis of movement.
        """
        if len(motor.axis) < 2 or not all(ax in motor.axis for ax in ["X", "Y"]):
            raise TypeError(
                "The provided motor must have both 'X' and 'Y' axes of movement."
                f" Available axes: {motor.axis}"
            )

        old_step, step = convert_to_target_egu(
            step,
            from_egu=step_egu,
            to_egu=motor.egu,
        )
        self.event_map.update(action.event_map)
        frames_per_side = frames // 4
        axis = ("X", "Y") if direction == "xy" else ("Y", "X")

        yield from bps.open_run()
        yield from bps.stage_all(*detectors)

        # main loop; it can only be interrupted when
        # a stop request is issued from the view and handled
        # by the presenter
        while True:
            # live acquisition; wait for scan action
            name, event = yield from rps.read_while_waiting(
                detectors,
                self.event_map,
                "live",
            )
            # if the plan has provided a different engineering unit
            # for the step size, set it accordingly
            if motor.egu != step_egu:
                yield from rps.set_property(motor, step, propr="step_size")

            yield from square_scan(
                detectors,
                motor,
                step,
                frames_per_side,
                axis,
            )

            if step != old_step:
                yield from rps.set_property(motor, old_step, propr="step_size")
            # clear the event and notify the action is done
            self.clear_and_notify(name, event)
            # then resume live acquisition (go back to the top of the loop)

    @continous
    def live_median_scan(
        self,
        detectors: Sequence[ReadableFlyer],
        motor: MotorProtocol,
        store_path: pathlib.Path,
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

        The plan combines the square scan movement in `live_square_scan`
        with the live streaming to disk in `live_stream`.
        Additionally, each detector will have a corresponding
        pseudo-model object that will compute the median
        of the frames collected during the square scan, making
        them available as stashed readings during the stream action,
        so that the computed medians are stored for post-processing and visualization
        by third-party tools.

        If the "stream" action is triggered before the "scan", there will be
        no median values available for streaming, but the plan will still stream
        the raw readings from the detectors.

        Parameters
        ----------
        - detectors: ``Sequence[DetectorProtocol]``
            - The detectors to use for data collection.
        - motor: ``MotorProtocol``
            - The motor to use for the scan movement.
            - It must provide two axes of movement ("X" and "Y").
        - store_path: ``pathlib.Path``
            - The folder path on disk where to store the median frames.
            - A Zarr subdirectory with a date-formatted name will be created
            inside this folder for each stream.
        - step: ``float``, optional
            - The step size for motor movement. Default is 1.0.
        - step_egu: ``Literal["um", "mm", "nm"]``, optional
            - The engineering unit for the step size.
            - Default is "um".
        - scan_frames: ``int``, optional
            - The number of frames to collect for median filtering.
            - The rectangular movement will be divided into four sides,
            each side collecting `frames / 4` frames, one frame per motor step.
            - Default is 20 (resulting in 4 frames per side).
        - direction: ``Literal["xy", "yx"]``, optional
            - The order of motor movement.
            - `xy`: move along X axis first, then Y axis.
            - `yx`: move along Y axis first, then X axis.
            - Default is "xy".
        - stream_frames: ``int``, optional
            - The number of frames to stream to disk when the stream action is triggered.
            - Default is 10.

        Raises
        ------
        - ``TypeError``
            - If `motor` does not provide both "X" and "Y" axis of movement.
        """
        if len(motor.axis) < 2 or not all(ax in motor.axis for ax in ["X", "Y"]):
            raise TypeError(
                "The provided motor must have both 'X' and 'Y' axes of movement."
                f" Available axes: {motor.axis}"
            )

        medians: set[MedianPseudoDevice] = set()
        for det in detectors:
            describe = yield from rps.describe(det)
            collect = yield from rps.describe_collect(det)
            medians.add(MedianPseudoDevice(det, describe, collect))

        axis = ("X", "Y") if direction == "xy" else ("Y", "X")
        self.event_map.update(**scan.event_map, **stream.event_map)
        old_step, step = convert_to_target_egu(
            step,
            from_egu=step_egu,
            to_egu=motor.egu,
        )

        live_stream = "live"
        stream_name = "stream"
        stream_declared = False

        # when streaming, we include the median
        # models in the set of objects to stage, kickoff, complete and collect,
        # so that the median values are included in the stream assets if
        # a previous scan action has been triggered
        objs: list[Readable[Any]] = [*detectors, *medians]

        yield from bps.open_run()
        yield from bps.stage_all(*detectors)

        while True:
            name, event = yield from rps.read_while_waiting(
                detectors,
                self.event_map,
                live_stream,
            )
            if name == scan.name:
                # make sure to clear the cache at each scan, to avoid stale data
                for median in medians:
                    yield from rps.clear_cache(median, wait=True)
                if motor.egu != step_egu:
                    yield from rps.set_property(motor, step, propr="step_size")
                yield from scan_and_stash(
                    detectors,
                    motor,
                    medians,  # type: ignore[arg-type]
                    step,
                    scan_frames // 4,
                    axis,
                )
                for median in medians:
                    # we have a stash of collected frames;
                    # call trigger to perform median calculation
                    yield from bps.trigger(median)
                if step != old_step:
                    yield from rps.set_property(motor, old_step, propr="step_size")

            elif name == stream.name:
                # update the set of detectors to include the median models,
                # so that the stream action can use the pre-computed median values
                # event triggered, start streaming to disk
                self.logger.debug("Starting data streaming to disk")

                # Create unique subdirectory for this streaming session
                timestamp = datetime.now().strftime("%d-%m-%Y_%H-%M-%S")
                acquisition_path = store_path / f"{timestamp}.zarr"
                acquisition_path.mkdir(parents=True, exist_ok=True)

                prepare_values: dict[str, Any] = {
                    "store_path": acquisition_path,
                    "capacity": stream_frames,
                    "write_forever": False,
                }

                for obj in objs:
                    yield from bps.prepare(obj, prepare_values, wait=True)

                if not stream_declared:
                    yield from bps.declare_stream(*objs, name=stream_name, collect=True)
                    stream_declared = True
                yield from bps.kickoff_all(*objs)

                # complete the streaming
                yield from bps.complete_all(*objs, wait=True)
                self.logger.debug("Flight complete.")

                # Explicitly collect the stream assets from all objects
                yield from bps.collect(*objs, name=stream_name)
            self.clear_and_notify(name, event)

    @continous(togglable=True)
    def live_stream(
        self,
        detectors: Sequence[ReadableFlyer],
        store_path: pathlib.Path,
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
        - store_path: ``pathlib.Path``
            - The folder path on disk where to store the Zarr data.
            - A Zarr subdirectory with a date-formatted name will be created
            inside this folder for each streaming session.
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
            # event triggered, start streaming to disk
            self.logger.debug("Starting data streaming to disk")

            # Create unique subdirectory for this streaming session
            timestamp = datetime.now().strftime("%d-%m-%Y_%H-%M-%S")
            acquisition_path = store_path / f"{timestamp}.zarr"
            acquisition_path.mkdir(parents=True, exist_ok=True)

            prepare_values: dict[str, Any] = {
                "store_path": acquisition_path,
                "capacity": frames,
                "write_forever": write_forever,
            }

            for detector in detectors:
                yield from bps.prepare(detector, prepare_values, wait=True)

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
            # Complete the streaming (wait for background thread to finish)
            yield from bps.complete_all(*detectors, wait=True)
            self.logger.debug("Flight complete.")

            # Explicitly collect the stream assets
            yield from bps.collect(*detectors, name=stream_name)

            # Mark stream as declared so future declarations skip
            stream_declared = True

            # we finished streaming;
            # clear the event and notify the action is done
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
        fut = self.engine(plan(*args, **kwargs))
        self.futures.add(fut)

        if not spec.togglable:
            # Single-shot plan: emit done when finished
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

    def _discard_future(self, fut: Future[Any]) -> None:
        # TODO: consider emitting a result
        # if the plan was not paused
        # and it also discards the future from the set
        if self.discard_by_pause:
            self.discard_by_pause = False
        self.futures.discard(fut)
