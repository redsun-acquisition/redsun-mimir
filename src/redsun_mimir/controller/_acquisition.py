from __future__ import annotations

from typing import TYPE_CHECKING

import bluesky.plans as bp
from bluesky.utils import RunEngineInterrupted
from sunflare.engine import RunEngine
from sunflare.log import Loggable
from sunflare.virtual import Publisher

from ..protocols import DetectorProtocol

if TYPE_CHECKING:
    from concurrent.futures import Future
    from typing import Any, Callable, Mapping, Sequence, Union

    from sunflare.engine import RunEngineResult
    from sunflare.model import ModelProtocol
    from sunflare.virtual import VirtualBus

    from ._config import AcquisitionControllerInfo


class AcquisitionController(Loggable, Publisher):
    def __init__(
        self,
        ctrl_info: AcquisitionControllerInfo,
        models: Mapping[str, ModelProtocol],
        virtual_bus: VirtualBus,
    ) -> None:
        Publisher.__init__(self, virtual_bus)
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
                self.error("An exception occurred during the plan: %s", exc)

        def live_count(toggle: bool, detectors: Sequence[str]) -> None:
            """Toggle a live acquisition.

            Parameters
            ----------
            toggle : bool
                Start or stop the live acquisition.
            detectors : ``Sequence[str]``
                The detectors to use in the live acquisition.
                Selected from the Acquisition widget combobox.

            """
            if toggle:
                self.debug("Starting live acquisition: %s", detectors)
                dets = [self.detectors[name] for name in detectors]
                self.fut = self.engine(bp.count(dets, num=None))
                self.fut.add_done_callback(_log_exception)
            else:
                try:
                    # stop raises an exception;
                    # we simply catch it and log it
                    self.engine.stop()
                except RunEngineInterrupted:
                    pass
                finally:
                    self.debug("Live ac quisition stopped.")

        self.plans: dict[str, Callable[..., None]] = {"Live count": live_count}

        self.ctrl_info.plans = self.plans

    def connection_phase(self) -> None:
        self.virtual_bus["AcquisitionWidget"]["sigToggleAcquisitionRequest"].connect(
            self.ctrl_info.plans["Live count"]
        )

    def _run_plan(self, plan: str, *args: Any, **kwargs: Any) -> None:
        self.plans[plan](*args, **kwargs)
