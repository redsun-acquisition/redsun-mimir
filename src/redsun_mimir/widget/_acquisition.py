from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, Sequence, cast, get_origin

from qtpy import QtWidgets
from sunflare.view.qt import BaseQtWidget
from sunflare.virtual import Signal

from redsun_mimir.controller import AcquisitionControllerInfo
from redsun_mimir.model import DetectorModelInfo
from redsun_mimir.utils.qt import CheckableComboBox, InfoDialog

if TYPE_CHECKING:
    import inspect
    from typing import Any

    from sunflare.config import RedSunSessionInfo
    from sunflare.virtual import VirtualBus


class AcquisitionWidget(BaseQtWidget):
    """Widget for the acquisition settings.

    Parameters
    ----------
    config : ``RedSunSessionInfo``
        Reference to the session configuration.
    virtual_bus : ``VirtualBus``
        Reference to the virtual bus.

    Attributes
    ----------
    sigLaunchPlanRequest : ``Signal[str, Sequence[str], dict[str, Any]]``
        Signal to launch a plan.
        - ``str``: The plan name.
        - ``Sequence[str]``: Sequence of device names involved in the plan.
        - ``dict[str, Any]``: Additional plan-specific keyword arguments.
    sigRequestPlansManifest : ``Signal``
        Signal to request the available plans from the underlying controller.

    """

    sigLaunchPlanRequest = Signal(str, object, object)
    sigRequestPlansManifest = Signal()

    def __init__(
        self,
        config: RedSunSessionInfo,
        virtual_bus: VirtualBus,
        *args: Any,
        **kwargs: Any,
    ):
        super().__init__(config, virtual_bus, *args, **kwargs)
        self.setWindowTitle("Acquisition settings")
        detectors = {
            name
            for name, _ in config.models.items()
            if isinstance(_, DetectorModelInfo)
        }
        ctrl_info = config.controllers["AcquisitionController"]
        assert isinstance(ctrl_info, AcquisitionControllerInfo)
        self.plans_info: dict[str, str] = {}

        self.plans_groupboxes: dict[str, QtWidgets.QGroupBox] = {}

        self.plans_combobox = QtWidgets.QComboBox(self)
        self.plans_combobox.setToolTip("Select a plan to run")
        self.info_btn = QtWidgets.QPushButton(self)
        self.info_btn.setToolTip("Information about the selected plan")
        self.info_btn.clicked.connect(self._on_info_clicked)
        pixmap = getattr(QtWidgets.QStyle, "SP_MessageBoxInformation")
        icon = cast("QtWidgets.QStyle", self.style()).standardIcon(pixmap)

        self.detectors_combobox = CheckableComboBox(self)
        self.info_btn.setIcon(icon)
        for name in detectors:
            self.detectors_combobox.addItem(name)

        self.action_btn = QtWidgets.QPushButton("Start", self)
        self.action_btn.setCheckable(True)
        self.action_btn.toggled.connect(self._on_action_toggled)

        layout = QtWidgets.QGridLayout()
        layout.addWidget(self.detectors_combobox, 0, 0, 1, 4)
        layout.addWidget(self.plans_combobox, 1, 0, 1, 3)
        layout.addWidget(self.info_btn, 1, 3)

        self.setLayout(layout)

    def registration_phase(self) -> None:
        self.virtual_bus.register_signals(self)

    def connection_phase(self) -> None:
        self.virtual_bus["AcquisitionController"]["sigPlansManifest"].connect(
            self._on_plans_manifest
        )
        self.sigRequestPlansManifest.emit()

    def _on_action_toggled(self, toggled: bool) -> None:
        plan = self.plans_combobox.currentText()
        detectors = self.detectors_combobox.checkedItems()
        self.sigLaunchPlanRequest.emit(plan, detectors, {"toggle": toggled})
        if toggled:
            self.action_btn.setText("Stop")
        else:
            self.action_btn.setText("Start")

    def _on_plans_manifest(self, manifests: dict[str, dict[str, Any]]) -> None:
        for name, manifest in manifests.items():
            self.plans_info[name] = manifest["docstring"]
            signature: inspect.Signature = manifest["signature"]
            self.plans_groupboxes[name] = QtWidgets.QGroupBox(self)
            for pid, pvalue in signature.parameters.items():
                if get_origin(pvalue.annotation) in (Sequence, Iterable):
                    ...

    def _on_info_clicked(self) -> None:
        info = self.plans_info[self.plans_combobox.currentText()]
        InfoDialog.show_dialog("Plan information", info, parent=self)
