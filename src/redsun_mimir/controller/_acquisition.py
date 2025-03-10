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
    from typing import Mapping, Sequence, Union

    from sunflare.engine import RunEngineResult
    from sunflare.model import ModelProtocol
    from sunflare.virtual import VirtualBus

    from ._config import AcquisitionControllerInfo


class AcquisitionController(Loggable, Publisher):
    
    def __init__(self, 
        ctrl_info: AcquisitionControllerInfo, 
        models: Mapping[str, ModelProtocol], 
        virtual_bus: VirtualBus
    ) -> None:
        Publisher.__init__(self, virtual_bus)
        self.ctrl_info = ctrl_info
        self.virtual_bus = virtual_bus
        self.detectors = {
            name: model for name, model in models.items() if isinstance(model, DetectorProtocol)
        }

        self.engine = RunEngine(socket_prefix="ACQ", socket=self.pub_socket)

        self.fut: Future[Union[RunEngineResult, tuple[str, ...]]]
    
    def registration_phase(self) -> None:
        self.virtual_bus.register_signals(self)

    def connection_phase(self) -> None:
        ...

    def _live_count(self, toggle: bool, detectors: Sequence[str]) -> None:
        if toggle:
            self.debug("Starting live acquisition: %s", detectors)
            dets = [self.detectors[name] for name in detectors]
            self.fut = self.engine(bp.count(dets, num=None))
        else:
            try:
                # stop raises an exceptiom;
                # we simply catch it and log it
                self.engine.stop()
            except RunEngineInterrupted:
                pass
            finally:
                self.debug("Live ac quisition stopped.")