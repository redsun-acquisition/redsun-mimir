from __future__ import annotations

from typing import TYPE_CHECKING

from qtpy import QtWidgets
from sunflare.view.qt import BaseQtWidget
from sunflare.virtual import Signal

from redsun_mimir.model import DetectorModelInfo

if TYPE_CHECKING:
    from typing import Any

    from bluesky.protocols import Descriptor, Reading
    from sunflare.config import RedSunSessionInfo
    from sunflare.virtual import VirtualBus


class DetectorWidget(BaseQtWidget):
    sigConfigRequest = Signal()

    def __init__(
        self,
        config: RedSunSessionInfo,
        virtual_bus: VirtualBus,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(config, virtual_bus, *args, **kwargs)
        self.detectors_info = {
            name: model_info
            for name, model_info in self.config.models.items()
            if isinstance(model_info, DetectorModelInfo)
        }

        self.detector_boxes: dict[str, QtWidgets.QGroupBox] = {}

    def registration_phase(self) -> None:
        self.virtual_bus.register_signals(self)

    def connection_phase(self) -> None:
        self.virtual_bus["DetectorController"]["sigDetectorConfigDescriptor"].connect(
            self._update_descriptor_ui
        )
        self.virtual_bus["DetectorController"]["sigDetectorConfigReading"].connect(
            self._update_reading_ui
        )

    def _update_descriptor_ui(
        self, detector: str, descriptor: dict[str, Descriptor]
    ) -> None:
        if detector not in self.detector_boxes:
            layout = QtWidgets.QFormLayout()
            self.detector_boxes[detector] = QtWidgets.QGroupBox(detector)
            for field, desc in descriptor.items():
                layout.addRow(QtWidgets.QLabel(field), QtWidgets.QLabel(str(desc)))

    def _update_reading_ui(
        self, detector: str, reading: dict[str, Reading[Any]]
    ) -> None: ...
