from __future__ import annotations

from typing import TYPE_CHECKING

from qtpy import QtWidgets
from sunflare.view.qt import BaseQtWidget
from sunflare.virtual import Signal

from redsun_mimir.model import DetectorModelInfo
from redsun_mimir.utils.qt import DescriptorTreeView

if TYPE_CHECKING:
    from typing import Any

    from bluesky.protocols import Descriptor, Reading
    from sunflare.config import RedSunSessionInfo
    from sunflare.virtual import VirtualBus


class DetectorWidget(BaseQtWidget):
    """Widget for displaying and editing detector configuration.

    Parameters
    ----------
    config : ``RedSunSessionInfo``
        Reference to the session configuration.
    virtual_bus : ``VirtualBus``
        Reference to the virtual bus.
    *args : Any
        Positional arguments.
    **kwargs : Any
        Keyword arguments.

    Attributes
    ----------
    sigConfigRequest : ``Signal``
        Signal for requesting configuration.
    sigPropertyChanged : ``Signal[str, dict[str, object]]``
        Signal for property changed.

        - ``str``: detector name.
        - ``dict[str, object]``: key-value pair of property and value.

    """

    sigConfigRequest = Signal()
    sigPropertyChanged = Signal(str, dict[str, object])

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
        self.tree = DescriptorTreeView(self)
        self.tree.model().sigStructureChanged.connect(self._on_structure_changed)
        self.tree.model().sigPropertyChanged.connect(self.sigPropertyChanged)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.tree)
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
    ) -> None:
        self.tree.model().add_device(detector, descriptor)

    def _update_parameter(
        self, detector: str, reading: dict[str, Reading[Any]]
    ) -> None:
        self.tree.model().update_readings(detector, reading)

    def _on_structure_changed(self) -> None:
        self.tree.expandAll()
        for i in range(self.tree.model().columnCount()):
            self.tree.resizeColumnToContents(i)
