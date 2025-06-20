import inspect
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Annotated, Any

import bluesky.plans as bp
from bluesky.utils import RunEngineInterrupted
from sunflare.engine import RunEngine
from sunflare.log import Loggable
from sunflare.model import ModelProtocol
from sunflare.virtual import Publisher, Signal, VirtualBus

from redsun_mimir.protocols import DetectorProtocol
from redsun_mimir.utils import togglable

from ._config import AcquisitionControllerInfo

if TYPE_CHECKING:
    from collections.abc import Callable

    from redsun_mimir.protocols import PlanManifest


class AcquisitionController(Publisher, Loggable):
    sigPlansManifest = Signal(object)
    sigPlanDone = Signal()

    def __init__(
        self,
        ctrl_info: AcquisitionControllerInfo,
        models: Mapping[str, ModelProtocol],
        virtual_bus: VirtualBus,
    ) -> None:
        super().__init__(virtual_bus)
        self.ctrl_info = ctrl_info
        self.virtual_bus = virtual_bus
        self.detectors = {
            name: model
            for name, model in models.items()
            if isinstance(model, DetectorProtocol)
        }

        self.engine = RunEngine(socket_prefix="ACQ", socket=self.pub_socket)

        @togglable
        def live_count(
            detectors: Annotated[
                Sequence[str], [det_name for det_name in self.detectors.keys()]
            ],
        ) -> str | None:
            """Start a live acquisition with the selected detectors.

            Parameters
            ----------
            detectors : ``Sequence[str]``
                The detectors to use in the live acquisition.

            Returns
            -------
            ``Future | str``
                The future object for the live acquisition.
                If no detectors are selected, a string error message is returned.
            """
            if len(detectors) == 0:
                error_msg = "No detectors selected for live count."
                return error_msg
            self.logger.debug("Starting live acquisition: %s", detectors)
            dets = [self.detectors[name] for name in detectors]
            self.engine(bp.count(dets, num=None))
            return None

        def snapshot(
            detectors: Annotated[
                Sequence[str], [det_name for det_name in self.detectors.keys()]
            ],
            frames: int,
        ) -> str | None:
            """Take one (or more) snapshots from each detector.

            Parameters
            ----------
            detectors: ``Sequence[str]``
                The detectors to take a snapshot from.
            frames: ``int``
                The number of snapshots to take for each detector.

            Returns
            -------
            ``Future | str``
                The future object for the snapshot.
                If no detectors are selected, a string error message is returned.
            """
            if len(detectors) == 0:
                error_msg = "No detectors selected for snapshot."
                return error_msg
            self.logger.debug("Taking snapshots: %s", detectors)
            dets = [self.detectors[name] for name in detectors]
            self.engine(bp.count(dets, num=frames))
            return None

        self.plans: dict[str, Callable[..., str | None]] = {
            "Live count": live_count,
            "Snapshot": snapshot,
        }

    def registration_phase(self) -> None:
        self.virtual_bus.register_signals(self)

    def connection_phase(self) -> None:
        self.virtual_bus["AcquisitionWidget"]["sigLaunchPlanRequest"].connect(
            self._run_plan
        )
        self.virtual_bus["AcquisitionWidget"]["sigStopPlanRequest"].connect(
            self._stop_plan
        )
        self.virtual_bus["AcquisitionWidget"]["sigRequestPlansManifest"].connect(
            self._send_plans_manifest
        )

    def _send_plans_manifest(self) -> None:
        manifest: dict[str, PlanManifest] = {}
        for name, plan in self.plans.items():
            docstr = inspect.getdoc(plan)
            annotations = inspect.get_annotations(plan)
            manifest.update(
                {
                    name: {
                        "docstring": docstr or "No information available",
                        "annotations": annotations,
                        "togglable": getattr(plan, "__togglable__", False),
                    }
                }
            )
        self.sigPlansManifest.emit(manifest)

    def _run_plan(self, plan: str, kwargs: dict[str, Any]) -> None:
        ret = self.plans[plan](**kwargs)
        if ret:
            self.logger.error(ret)

    def _stop_plan(self) -> None:
        if self.engine.state == "running":
            try:
                self.engine.stop()
            except RunEngineInterrupted:
                # silently ignore the exception
                pass
