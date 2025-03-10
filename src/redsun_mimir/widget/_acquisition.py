from __future__ import annotations

from typing import TYPE_CHECKING

from sunflare.view.qt import BaseQtWidget
from sunflare.virtual import Signal

from redsun_mimir.model import DetectorModelInfo

if TYPE_CHECKING:
    from typing import Any

    from sunflare.config import RedSunSessionInfo
    from sunflare.virtual import VirtualBus


class AcquisitionWidget(BaseQtWidget):

    sigToggleAcquisitionRequest = Signal(bool, list[str])

    def __init__(
        self, 
        config: RedSunSessionInfo, 
        virtual_bus: VirtualBus, 
        *args: Any, 
        **kwargs: Any
    ):
        super().__init__(config, virtual_bus, *args, **kwargs)
        self.setWindowTitle("Acquisition settings")
        self.detectors_info = {
            name: model for name, model in config.models.items() if isinstance(model, DetectorModelInfo)
        }
