from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence  # noqa: TC003
from typing import TYPE_CHECKING, Literal
from typing import Annotated as Ann

import bluesky.plan_stubs as bps
import in_n_out as ino
from bluesky.utils import MsgGenerator  # noqa: TC002
from sunflare.engine import RunEngine
from sunflare.log import Loggable
from sunflare.presenter import PPresenter
from sunflare.virtual import Signal, VirtualBus

import redsun_mimir.plan_stubs as rps
from redsun_mimir.actions import ActionList, actioned
from redsun_mimir.common import (
    PlanSpec,
    collect_arguments,
    create_plan_spec,
    register_bound_command,
    resolve_arguments,
    wait_for_actions,
)
from redsun_mimir.protocols import DetectorProtocol, MotorProtocol  # noqa: TC001

if TYPE_CHECKING:
    from concurrent.futures import Future
    from typing import Any, Callable, Mapping

    from sunflare.model import PModel

    from ._config import AcquisitionControllerInfo

store = ino.Store.create("plan_specs")


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
    ``tulpe[float, float]``
        A tuple with two values, in the following order:
        - The original step value in the source engineering unit.
        - The converted step value in the target engineering unit.
    """
    old_step = step
    if from_egu == to_egu:
        return old_step, step

    to_meters = {
        "nm": 1e-9,
        "μm": 1e-6,
        "mm": 1e-3,
    }

    # convert to meters first, then to target egu
    new_step = step * to_meters[from_egu] / to_meters[to_egu]

    return new_step, old_step


class AcquisitionController(PPresenter, Loggable):
    """A centralized acquisition presenter to manage a Bluesky run engine.

    Parameters
    ----------
    ctrl_info : ``AcquisitionControllerInfo``
        The acquisition presenter configuration information.
    models : ``Mapping[str, PModel]``
        The available models in the application.
    virtual_bus : ``VirtualBus``
        The virtual bus to register signals on.

    Attributes
    ----------
    sigPlanDone : ``Signal``
        Signal emitted when a plan is done.
    sigActionDone : ``Signal[str]``
        Signal emitted when an action is done.
    """

    sigPlanDone = Signal()
    sigActionDone = Signal(str)

    def __init__(
        self,
        ctrl_info: AcquisitionControllerInfo,
        models: Mapping[str, PModel],
        virtual_bus: VirtualBus,
    ) -> None:
        self.ctrl_info = ctrl_info
        self.virtual_bus = virtual_bus
        self.models = models
        self.engine = RunEngine()
        register_bound_command(self.engine, wait_for_actions)

        self.futures: set[Future[Any]] = set()
        self.event_map: dict[str, asyncio.Event] = {}
        self.discard_by_pause = False
        self.expected_presenters = frozenset(["DetectorController", "MedianPresenter"])

        self.plans: dict[str, Callable[..., MsgGenerator[Any]]] = {
            "live_count": self.live_count,
            "live_square_scan": self.live_square_scan,
            "snap": self.snap,
        }
        self.plan_specs: dict[str, PlanSpec] = {
            name: create_plan_spec(plan, models) for name, plan in self.plans.items()
        }

        store.register_provider(self.plans_specificiers)

    def registration_phase(self) -> None:
        self.virtual_bus.register_signals(self)

    def connection_phase(self) -> None:
        self.virtual_bus.signals["AcquisitionWidget"]["sigLaunchPlanRequest"].connect(
            self.launch_plan
        )
        self.virtual_bus.signals["AcquisitionWidget"]["sigStopPlanRequest"].connect(
            self.stop_plan
        )
        self.virtual_bus.signals["AcquisitionWidget"]["sigPauseResumeRequest"].connect(
            self.pause_or_resume_plan
        )
        self.virtual_bus.signals["AcquisitionWidget"]["sigActionRequest"].connect(
            self.set_action_event
        )

        for name, callback in self.virtual_bus.callbacks.items():
            if name in self.expected_presenters:
                self.engine.subscribe(callback)

    def plans_specificiers(self) -> set[PlanSpec]:
        return set(self.plan_specs.values())

    @actioned(togglable=True, pausable=True)
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

    @actioned(togglable=True)
    def live_square_scan(
        self,
        detectors: Sequence[DetectorProtocol],
        motor: MotorProtocol,
        step: float = 1.0,
        step_egu: Literal["μm", "mm", "nm"] = "μm",
        frames: int = 100,
        direction: Literal["xy", "yx"] = "xy",
        /,
        actions: Ann[list[str], ActionList()] = ["scan"],
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
        - step_egu: ``Literal["μm", "mm", "nm"]``, optional
            - The engineering unit for the step size.
            - Default is "μm".
        - frames: ``int``, optional
            - The number of frames to collect for median filtering.
            - The rectangular movement will be divided into four sides,
            each side collecting `frames / 4` frames, one frame per motor step.
            - Default is 100 (resulting in 25 frames per side).
        - direction: ``Literal["xy", "yx"]``, optional
            - The order of motor movement.
            - `xy`: move along X axis first, then Y axis.
            - `yx`: move along Y axis first, then X axis.

        Raises
        ------
        - ``TypeError``
            - If `motor` does not provide both "X" and "Y" axis of movement.
        """
        if len(motor.model_info.axis) < 2 or not all(
            ax in motor.model_info.axis for ax in ["X", "Y"]
        ):
            raise TypeError(
                "The provided motor must have both 'X' and 'Y' axes of movement."
                f" Available axes: {motor.model_info.axis}"
            )

        old_step, step = convert_to_target_egu(
            step,
            from_egu=step_egu,
            to_egu=motor.model_info.egu,
        )
        self.event_map.update({name: asyncio.Event() for name in actions})
        frames_per_side = frames // 4
        axis = ("X", "Y") if direction == "xy" else ("Y", "X")

        yield from bps.open_run()
        yield from bps.stage_all(*detectors)

        live_stream = "live"
        scan_stream = "square_scan"

        # main loop; it can only be interrupted when
        # a stop request is issued from the view and handled
        # by the presenter
        while True:
            # live acquisition; wait for scan action
            name, event = yield from rps.read_while_waiting(
                detectors,
                self.event_map,
                live_stream,
            )
            # if the plan has provided a different engineering unit
            # for the step size, set it accordingly
            if motor.model_info.egu != step_egu:
                yield from rps.set_proprerty(motor, step, propr="step_size")

            # first scan on the positive direction...
            for idx in range(2):
                ax = axis[idx]
                # ... set the axis direction and the step size ...
                yield from rps.set_proprerty(motor, ax, propr="axis")
                for _ in range(frames_per_side):
                    # ... take a snapshot and move one step ...
                    yield from bps.trigger_and_read(detectors, scan_stream)
                    yield from bps.mvr(motor, step)
            # ... then scan on the negative direction ...
            for idx in range(2):
                ax = axis[1 - idx]
                yield from rps.set_proprerty(motor, ax, propr="axis")
                for _ in range(frames_per_side):
                    yield from bps.trigger_and_read(detectors, scan_stream)
                    yield from bps.mvr(motor, -step)
            # ... if needed, reset the step size ...
            if step != old_step:
                yield from rps.set_proprerty(motor, old_step, propr="step_size")
            # ... clear the event and notify the action is done ...
            self.clear_and_notify(name, event)
            # ... then resume live acquisition

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

    def clear_and_notify(self, name: str, event: asyncio.Event) -> None:
        """Clear the given event and emit "action done" signal.

        Parameters
        ----------
        event : ``asyncio.Event``
            The event to clear and notify.
        """
        event.clear()
        self.sigActionDone.emit(name)

    def set_action_event(self, action_name: str) -> None:
        event = self.event_map[action_name]
        self.engine.loop.call_soon_threadsafe(event.set)

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
