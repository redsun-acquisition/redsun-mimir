from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Annotated, cast, get_args, get_origin

from qtpy import QtCore, QtWidgets
from sunflare.view.qt import BaseQtWidget
from sunflare.virtual import Signal

from redsun_mimir.utils.qt import CheckableComboBox, ConfigurationGroupBox, InfoDialog

if TYPE_CHECKING:
    from typing import Any

    from sunflare.config import RedSunSessionInfo
    from sunflare.virtual import VirtualBus

    from redsun_mimir.protocols import PlanManifest


# TODO: these functions
# could be replaced by
# magicgui (and they should)
def create_combobox(
    parent: QtWidgets.QWidget,
    layout: QtWidgets.QFormLayout,
    name: str,
    default: list[str],
) -> None:
    cbox = CheckableComboBox(parent)
    cbox.addItems(default)
    layout.addRow(name, cbox)


def create_checkbox(
    parent: QtWidgets.QWidget, layout: QtWidgets.QFormLayout, name: str, default: bool
) -> None:
    widget = QtWidgets.QCheckBox(parent)
    widget.setChecked(default)
    layout.addRow(name, widget)


def create_spinbox(
    parent: QtWidgets.QWidget, layout: QtWidgets.QFormLayout, name: str, default: int
) -> None:
    widget = QtWidgets.QSpinBox(parent)
    widget.setValue(default)
    layout.addRow(name, widget)


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
        - ``dict[str, Any]``: Additional plan-specific keyword arguments.
    sigRequestPlansManifest : ``Signal``
        Signal to request the available plans from the underlying controller.

    """

    sigLaunchPlanRequest = Signal(str, object)
    sigRequestPlansManifest = Signal()

    def __init__(
        self,
        config: RedSunSessionInfo,
        virtual_bus: VirtualBus,
        *args: Any,
        **kwargs: Any,
    ):
        super().__init__(config, virtual_bus, *args, **kwargs)
        self.plans_info: dict[str, str] = {}

        self.plans_groupboxes: dict[str, ConfigurationGroupBox] = {}
        self.run_buttons: dict[str, QtWidgets.QPushButton] = {}

        self.plans_combobox = QtWidgets.QComboBox(self)
        self.plans_combobox.setToolTip("Select a plan to run")
        self.info_btn = QtWidgets.QPushButton(self)
        self.info_btn.setIcon(
            cast("QtWidgets.QStyle", self.style()).standardIcon(
                QtWidgets.QStyle.StandardPixmap.SP_FileDialogInfoView
            )
        )
        self.info_btn.setToolTip("Information about the selected plan")
        button_size = QtCore.QSize(24, 24)
        self.info_btn.setMinimumSize(button_size)
        self.info_btn.setMaximumSize(button_size)
        self.info_btn.setIconSize(QtCore.QSize(16, 16))
        self.info_btn.setFlat(True)
        self.info_btn.clicked.connect(self._on_info_clicked)

        top_layout = QtWidgets.QHBoxLayout()
        top_layout.addWidget(self.plans_combobox, 1)
        top_layout.addWidget(self.info_btn, 0)

        self.groups_container = QtWidgets.QWidget()
        self.groups_layout = QtWidgets.QVBoxLayout(self.groups_container)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(top_layout)
        layout.addWidget(self.groups_container)

        self.plans_combobox.currentTextChanged.connect(self._on_plan_changed)

    def _on_plan_changed(self, text: str) -> None:
        for name, groupbox in self.plans_groupboxes.items():
            if name == text:
                groupbox.show()
            else:
                groupbox.hide()

    def registration_phase(self) -> None:
        self.virtual_bus.register_signals(self)

    def connection_phase(self) -> None:
        self.virtual_bus["AcquisitionController"]["sigPlansManifest"].connect(
            self._on_plans_manifest
        )
        self.virtual_bus["AcquisitionController"]["sigPlanDone"].connect(
            self._on_plan_done
        )
        self.sigRequestPlansManifest.emit()

    def _on_action_toggled(self, toggled: bool) -> None:
        plan = self.plans_combobox.currentText()
        configuration = self.plans_groupboxes[plan].configuration()
        configuration.update({"toggle": toggled})
        self.plans_combobox.setEnabled(not toggled)
        self.plans_groupboxes[plan].setEnabled(not toggled)
        self.sigLaunchPlanRequest.emit(plan, configuration)
        if toggled:
            self.run_buttons[plan].setText("Stop")
        else:
            self.run_buttons[plan].setText("Run")

    def _on_action_requested(self) -> None:
        plan = self.plans_combobox.currentText()
        configuration = self.plans_groupboxes[plan].configuration()
        self.sigLaunchPlanRequest.emit(plan, configuration)
        self.plans_groupboxes[plan].setEnabled(False)
        self.run_buttons[plan].setEnabled(False)

    def _on_plans_manifest(self, manifests: dict[str, PlanManifest]) -> None:
        names = list(manifests.keys())
        self.plans_combobox.addItems(names)
        self.plans_combobox.setCurrentText(names[0])
        for name, manifest in manifests.items():
            is_togglable = False
            self.plans_info[name] = manifest["docstring"]
            layout = QtWidgets.QFormLayout(self)
            groupbox = ConfigurationGroupBox(layout, self)
            annotations = manifest["annotations"]
            for key, value in annotations.items():
                if key == "toggle":
                    # skip the toggle argument;
                    # mark the plan as togglable
                    # and continue
                    is_togglable = True
                    continue
                if get_origin(value) is Annotated:
                    args = get_args(value)
                    type_hint = args[0]
                    metadata = args[1:]
                    if get_origin(type_hint) in (Sequence, Iterable):
                        create_combobox(self, layout, key, metadata[-1])
                    elif type_hint is bool:
                        create_checkbox(self, layout, key, False)
                    elif type_hint is int:
                        create_spinbox(self, layout, key, 0)
                    else:
                        raise TypeError(f"Unsupported type: {type_hint}")

            self.run_buttons[name] = QtWidgets.QPushButton("Run", groupbox)
            if is_togglable:
                self.run_buttons[name].setCheckable(True)
                self.run_buttons[name].toggled.connect(self._on_action_toggled)
            else:
                self.run_buttons[name].clicked.connect(self._on_action_requested)

            groupbox.hide()
            if name == self.plans_combobox.currentText():
                groupbox.show()
            layout.addRow(self.run_buttons[name])
            groupbox.setLayout(layout)
            self.groups_layout.addWidget(groupbox)
            self.plans_groupboxes[name] = groupbox

    def _on_plan_done(self) -> None:
        plan = self.plans_combobox.currentText()
        self.plans_groupboxes[plan].setEnabled(True)
        self.run_buttons[plan].setEnabled(True)

    def _on_info_clicked(self) -> None:
        info = self.plans_info[self.plans_combobox.currentText()]
        InfoDialog.show_dialog("Plan information", info, parent=self)
