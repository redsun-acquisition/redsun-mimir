from __future__ import annotations

from collections.abc import Mapping, Sequence  # noqa: TC003
from threading import Event
from typing import TYPE_CHECKING

import bluesky.plan_stubs as bps
import in_n_out as ino
from bluesky.plans import count
from bluesky.utils import MsgGenerator  # noqa: TC002
from sunflare.engine import RunEngine
from sunflare.log import Loggable
from sunflare.virtual import Signal, VirtualBus

from redsun_mimir.common import PlanManifest, filter_models, generate_plan_manifest
from redsun_mimir.protocols import DetectorProtocol  # noqa: TC001
from redsun_mimir.utils import togglable

if TYPE_CHECKING:
    from concurrent.futures import Future
    from typing import Any, Callable, Mapping

    from sunflare.model import ModelProtocol

    from ._config import AcquisitionControllerInfo

store = ino.Store.create("PlanManifest")


class AcquisitionController(Loggable):
    sigPlanDone = Signal(object)
    sigNewDocument = Signal(str, object)

    def __init__(
        self,
        ctrl_info: AcquisitionControllerInfo,
        models: Mapping[str, ModelProtocol],
        virtual_bus: VirtualBus,
    ) -> None:
        self.ctrl_info = ctrl_info
        self.virtual_bus = virtual_bus
        self.models = models
        self.live_event = Event()
        self.engine = RunEngine()
        self._sig_token = self.engine.subscribe(self.sigNewDocument)
        self.futures: set[Future[Any]] = set()

        self.plans: dict[str, Callable[..., MsgGenerator[Any]]] = {
            "live_count": self.live_count,
            "snap": self.snap,
        }
        self.manifests: set[PlanManifest] = set(
            [generate_plan_manifest(plan, models) for plan in self.plans.values()]
        )

        store.register_provider(self.plans_manifests)

    def registration_phase(self) -> None:
        self.virtual_bus.register_signals(self)

    def connection_phase(self) -> None:
        self.virtual_bus["AcquisitionWidget"]["sigLaunchPlanRequest"].connect(
            self.launch_plan
        )
        self.virtual_bus["AcquisitionWidget"]["sigStopPlanRequest"].connect(
            self.stop_plan
        )

    def plans_manifests(self) -> set[PlanManifest]:
        return self.manifests

    @togglable
    def live_count(self, detectors: Sequence[DetectorProtocol]) -> MsgGenerator[None]:
        """Start a live acquisition with the selected detectors.

        Parameters
        ----------
        detectors : ``Sequence[DetectorProtocol]``
            The detectors to use in the live acquisition.
        """
        self.logger.debug("Starting live count acquisition.")
        yield from bps.open_run()
        yield from bps.stage_all(*detectors)
        while self.live_event.is_set():
            yield from bps.trigger_and_read(detectors, name="live")
        yield from bps.unstage_all(*detectors)
        yield from bps.close_run(exit_status="success")
        self.logger.debug("Live count acquisition stopped.")

    def snap(
        self, detectors: Sequence[DetectorProtocol], frames: int = 1
    ) -> MsgGenerator[None]:
        """Take ``num_frames`` snapshot from each detector.

        Parameters
        ----------
        detectors : ``Sequence[DetectorProtocol]``
            The detectors to take a snapshot from.
        num_frames : ``int``, optional
            The number of snapshots to take for each detector.
            Must be a non-zero, positive integer.
            Default is 1.
        """
        if frames <= 0:
            raise ValueError("Number of frames must be a positive integer.")

        self.logger.debug("Taking %d frame(s) snapshot.", frames)
        yield from count(detectors, num=frames)
        self.logger.debug("Snapshot acquisition finished.")

    def launch_plan(self, plan: str, togglable: bool, kwargs: dict[str, Any]) -> None:
        """Launch the specified plan.

        Parameters
        ----------
        plan : ``str``
            The name of the plan to launch.
        togglable : ``bool``
            Whether the plan is togglable.
        kwargs : ``dict[str, Any]``
            Keyword arguments to pass to the plan.
        """
        plan_func = self.plans[plan]
        for name, arg in kwargs.items():
            if type(arg) is tuple and len(arg) == 2:
                # view packs the annotation and value in a tuple
                # for models; unpack it and update the kwargs
                # with the actual models
                choices = filter_models(self.models, arg[0], arg[1])
                kwargs[name] = choices
        if togglable:
            # TODO: this imposes the constraint that
            # plans always have to refer to the local
            # live_event obj; maybe it should be
            # passed as an argument to the plan?
            self.live_event.set()
        fut = self.engine(plan_func(**kwargs))
        self.futures.add(fut)

        # TODO: add a specific callback that emits
        # a possible result object from the future,
        # and it also discards the future from the set
        fut.add_done_callback(self.futures.discard)

    def stop_plan(self) -> None:
        """Stop the running plan."""
        if self.live_event.is_set():
            self.live_event.clear()
            self.logger.debug("Stopping live plan.")
        else:
            self.engine.stop()
