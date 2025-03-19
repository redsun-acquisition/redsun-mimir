from __future__ import annotations

from typing import TYPE_CHECKING

from qtpy import QtWidgets
from sunflare.view.qt import BaseQtWidget
from sunflare.virtual import Signal

from redsun_mimir.model import DetectorModelInfo
from redsun_mimir.utils.qt import DescriptorModel

if TYPE_CHECKING:
    from typing import Any

    from bluesky.protocols import Descriptor, Reading
    from sunflare.config import RedSunSessionInfo
    from sunflare.virtual import VirtualBus

DESCRIPTOR_MAP = {
    "string": "str",
    "number": "float",
    "array": "list",
    "boolean": "bool",
    "integer": "int",
}


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
        self.tree_model = DescriptorModel()
        self.tree_view = QtWidgets.QTreeView()
        self.tree_view.setModel(self.tree_model)
        self.tree_view.setAlternatingRowColors(True)

        self.tree_model.sigStructureChanged.connect(self._on_structure_changed)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.tree_view)
        self.setLayout(layout)

    def registration_phase(self) -> None:
        self.virtual_bus.register_signals(self)

    def connection_phase(self) -> None:
        self.virtual_bus["DetectorController"]["sigDetectorConfigDescriptor"].connect(
            self._update_parameter_layout
        )
        self.virtual_bus["DetectorController"]["sigDetectorConfigReading"].connect(
            self._update_parameter
        )

    def _update_parameter_layout(
        self, detector: str, descriptor: dict[str, Descriptor]
    ) -> None: ...

    def _update_parameter(
        self, detector: str, reading: dict[str, Reading[Any]]
    ) -> None: ...

    def _on_structure_changed(self) -> None:
        self.tree_view.expandAll()
        for i in range(self.tree_model.columnCount()):
            self.tree_view.resizeColumnToContents(i)
