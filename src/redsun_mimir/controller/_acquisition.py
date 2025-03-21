from __future__ import annotations

import inspect
import logging
from typing import TYPE_CHECKING

import bluesky.plans as bp
from bluesky.utils import RunEngineInterrupted
from sunflare.engine import RunEngine
from sunflare.virtual import Publisher

from ..protocols import DetectorProtocol

if TYPE_CHECKING:
    from concurrent.futures import Future
    from typing import Any, Callable, Mapping, Sequence, Union

    from sunflare.engine import RunEngineResult
    from sunflare.model import ModelProtocol
    from sunflare.virtual import VirtualBus

    from ._config import AcquisitionControllerInfo


class AcquisitionController(Publisher):
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

        self._logger = logging.getLogger("redsun")
        self._log_extras = {
            "clsname": self.__class__.__name__,
        }

        def _log_exception(
            fut: Future[Union[RunEngineResult, tuple[str, ...]]],
        ) -> None:
            try:
                fut.result()
            except Exception as exc:
                self._logger.error(
                    "An exception occurred during the plan: %s",
                    exc,
                    extra=self._log_extras,
                )

        def live_count(detectors: Sequence[str], toggle: bool) -> None:
            """Toggle a live acquisition.

            Parameters
            ----------
            detectors : ``Sequence[str]``
                The detectors to use in the live acquisition.
                Selected from the Acquisition widget combobox.
            toggle : ``bool``
                Toggle the live acquisition on or off.

            """
            if toggle:
                self._logger.debug(
                    "Starting live acquisition: %s", detectors, extra=self._log_extras
                )
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
                    self._logger.debug(
                        "Live ac quisition stopped.", extra=self._log_extras
                    )

        self.plans: dict[str, Callable[..., None]] = {"Live count": live_count}

        self.ctrl_info.plans = {
            plan: inspect.getdoc(func) for plan, func in self.plans.items()
        }

    def connection_phase(self) -> None:
        self.virtual_bus["AcquisitionWidget"]["sigLaunchPlanRequest"].connect(
            self._run_plan
        )

    def _run_plan(
        self, plan: str, devices: Sequence[str], kwargs: dict[str, Any]
    ) -> None:
        try:
            self.plans[plan](devices, **kwargs)
        except TypeError as exc:
            self._logger.error(
                f'Incorrect parameters for "{plan}": {exc}', extra=self._log_extras
            )
