from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Annotated, get_type_hints

import bluesky.plans as bp
from bluesky.utils import RunEngineInterrupted
from sunflare.engine import RunEngine
from sunflare.log import Loggable
from sunflare.virtual import Publisher, Signal

from redsun_mimir.protocols import DetectorProtocol

if TYPE_CHECKING:
    from concurrent.futures import Future
    from typing import Any, Callable, Mapping, Sequence, Union

    from sunflare.engine import RunEngineResult
    from sunflare.model import ModelProtocol
    from sunflare.virtual import VirtualBus

    from redsun_mimir.protocols import PlanManifest

    from ._config import AcquisitionControllerInfo


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

        self.fut: Future[Union[RunEngineResult, tuple[str, ...]]]

        def _log_exception(
            fut: Future[Union[RunEngineResult, tuple[str, ...]]],
        ) -> None:
            try:
                fut.result()
            except Exception as exc:
                self.logger.error(
                    "An exception occurred during the plan: %s",
                    exc,
                )

        def _plan_done(
            fut: Future[Union[RunEngineResult, tuple[str, ...]]],
        ) -> None:
            try:
                fut.result()
            except Exception:
                # exception handled by _log_exception
                pass
            finally:
                self.sigPlanDone.emit()

        def live_count(
            detectors: Annotated[Sequence[str], list(self.detectors.keys())],
            toggle: bool,
        ) -> None:
            """Toggle a live acquisition.

            Parameters
            ----------
            detectors : ``Sequence[str]``
                The detectors to use in the live acquisition.
            toggle : ``bool``
                Toggle the live acquisition on or off.

            """
            if toggle:
                self.logger.debug("Starting live acquisition: %s", detectors)
                dets = [self.detectors[name] for name in detectors]
                self.fut = self.engine(bp.count(dets, num=None))
                self.fut.add_done_callback(_log_exception)
            else:
                try:
                    # stop raises an exception;
                    # we simply catch it
                    self.engine.stop()
                except RunEngineInterrupted:
                    pass
                finally:
                    self.logger.debug("Live acquisition stopped.")

        def snapshot(
            detectors: Annotated[Sequence[str], list(self.detectors.keys())],
            frames: int,
        ) -> None:
            """Take one (or more) snapshots from each detector.

            Parameters
            ----------
            detectors: ``Sequence[str]``
                The detectors to take a snapshot from.
            frames: ``int``
                The number of snapshots to take for each detector.
            """
            self.logger.debug("Taking snapshots: %s", detectors)
            dets = [self.detectors[name] for name in detectors]
            self.fut = self.engine(bp.count(dets, num=frames))
            self.fut.add_done_callback(_log_exception)
            self.fut.add_done_callback(_plan_done)

        self.plans: dict[str, Callable[..., None]] = {
            "Live count": live_count,
            "Snapshot": snapshot,
        }

    def connection_phase(self) -> None:
        self.virtual_bus["AcquisitionWidget"]["sigLaunchPlanRequest"].connect(
            self._run_plan
        )
        self.virtual_bus["AcquisitionWidget"]["sigRequestPlansManifest"].connect(
            self._send_plans_manifest
        )

    def _send_plans_manifest(self) -> None:
        for name, plan in self.plans.items():
            docstr = inspect.getdoc(plan)
            annotations = get_type_hints(plan, include_extras=True)
            manifest: dict[str, PlanManifest] = {
                name: {
                    "docstring": docstr or "No docstring available",
                    "annotations": annotations,
                }
            }
        self.sigPlansManifest.emit(manifest)

    def _run_plan(self, plan: str, kwargs: dict[str, Any]) -> None:
        try:
            self.plans[plan](**kwargs)
        except TypeError as exc:
            self.logger.error(f'Incorrect parameters for "{plan}": {exc}')
