from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Annotated, NamedTuple, cast, get_args, get_origin

from qtpy import QtCore
from qtpy import QtWidgets as QtW
from sunflare.log import Loggable
from sunflare.view.qt import BaseQtWidget
from sunflare.virtual import Signal

from redsun_mimir.utils.qt import CheckableComboBox, ConfigurationGroupBox, InfoDialog

if TYPE_CHECKING:
    from typing import Any

    from sunflare.config import ViewInfoProtocol
    from sunflare.virtual import VirtualBus

    from redsun_mimir.protocols import PlanManifest


# TODO: these functions
# could be replaced by
# magicgui (and they should)
def create_combobox(
    parent: QtW.QWidget,
    layout: QtW.QFormLayout,
    name: str,
    default: list[str],
) -> None:
    cbox = CheckableComboBox(parent)
    cbox.addItems(default)
    layout.addRow(name, cbox)


def create_checkbox(
    parent: QtW.QWidget, layout: QtW.QFormLayout, name: str, default: bool
) -> None:
    widget = QtW.QCheckBox(parent)
    widget.setChecked(default)
    layout.addRow(name, widget)


def create_spinbox(
    parent: QtW.QWidget, layout: QtW.QFormLayout, name: str, default: int
) -> None:
    widget = QtW.QSpinBox(parent)
    widget.setValue(default)
    layout.addRow(name, widget)


class PlanWidget(NamedTuple):
    group: ConfigurationGroupBox
    run: QtW.QPushButton

    def setEnabled(self, enabled: bool) -> None:
        self.group.setEnabled(enabled)
        self.run.setEnabled(enabled)

    def hide(self) -> None:
        self.group.hide()
        self.run.hide()

    def show(self) -> None:
        self.group.show()
        self.run.show()


class AcquisitionWidget(BaseQtWidget, Loggable):
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
    sigStopPlanRequest : ``Signal[str]``
        Signal to stop a running plan.
        - ``str``: The plan name.
    sigRequestPlansManifest : ``Signal``
        Signal to request the available plans from the underlying controller.

    """

    sigLaunchPlanRequest = Signal(str, object)
    sigStopPlanRequest = Signal(str)
    sigRequestPlansManifest = Signal()

    def __init__(
        self,
        view_info: ViewInfoProtocol,
        virtual_bus: VirtualBus,
        *args: Any,
        **kwargs: Any,
    ):
        super().__init__(view_info, virtual_bus, *args, **kwargs)
        self.plans_info: dict[str, str] = {}

        self.plan_widgets: dict[str, PlanWidget] = {}

        self.plans_combobox = QtW.QComboBox(self)
        self.plans_combobox.setToolTip("Select a plan to run")
        self.info_btn = QtW.QPushButton(self)
        self.info_btn.setIcon(
            cast("QtW.QStyle", self.style()).standardIcon(
                QtW.QStyle.StandardPixmap.SP_FileDialogInfoView
            )
        )
        self.info_btn.setToolTip("Information about the selected plan")
        button_size = QtCore.QSize(24, 24)
        self.info_btn.setMinimumSize(button_size)
        self.info_btn.setMaximumSize(button_size)
        self.info_btn.setIconSize(QtCore.QSize(16, 16))
        self.info_btn.setFlat(True)
        self.info_btn.clicked.connect(self._on_info_clicked)

        top_layout = QtW.QHBoxLayout()
        top_layout.addWidget(self.plans_combobox, 1)
        top_layout.addWidget(self.info_btn, 0)

        self.groups_layout = QtW.QVBoxLayout()
        self.button_layout = QtW.QHBoxLayout()

        layout = QtW.QVBoxLayout(self)
        layout.addLayout(top_layout)
        layout.addLayout(self.groups_layout)
        layout.addLayout(self.button_layout)

        self.plans_combobox.currentTextChanged.connect(self._on_plan_changed)
        self.setLayout(layout)

    def _on_plan_changed(self, text: str) -> None:
        for name, widget in self.plan_widgets.items():
            if name == text:
                widget.show()
            else:
                widget.hide()
        self.adjustSize()

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
        self.plans_combobox.setEnabled(not toggled)
        self.plan_widgets[plan].group.setEnabled(not toggled)
        if toggled:
            configuration = self.plan_widgets[plan].group.configuration()
            self.sigLaunchPlanRequest.emit(plan, configuration)
            self.plan_widgets[plan].run.setText("Stop")
        else:
            self.sigStopPlanRequest.emit(plan)
            self.plan_widgets[plan].run.setText("Run")

    def _on_action_requested(self) -> None:
        plan = self.plans_combobox.currentText()
        configuration = self.plan_widgets[plan].group.configuration()
        self.sigLaunchPlanRequest.emit(plan, configuration)
        self.plan_widgets[plan].setEnabled(False)

    def _on_plans_manifest(self, manifests: dict[str, PlanManifest]) -> None:
        names = list(manifests.keys())
        self.plans_combobox.addItems(names)
        self.plans_combobox.setCurrentText(names[0])
        for name, manifest in manifests.items():
            is_togglable = manifest.is_toggleable
            self.plans_info[name] = manifest.description
            layout = QtW.QFormLayout()
            groupbox = ConfigurationGroupBox()
            annotations = manifest["annotations"]  # type: ignore
            for key, annotation in annotations.items():
                if key == "return":
                    # skip the return argument
                    continue
                if get_origin(annotation) is Annotated:
                    # annotated type
                    args = get_args(annotation)
                    type_hint = args[0]
                    metadata = args[1:]
                    # TODO: how to treat metadata
                    # for non-sequence types?
                    if get_origin(type_hint) in (Sequence, Iterable):
                        create_combobox(self, layout, key, metadata[-1])
                    elif type_hint is bool:
                        create_checkbox(self, layout, key, False)
                    elif type_hint is int:
                        create_spinbox(self, layout, key, 1)
                    else:
                        self.logger.warning("Unsupported type %s, skipping.", type_hint)
                else:
                    if annotation is bool:
                        create_checkbox(self, layout, key, False)
                    elif annotation is int:
                        create_spinbox(self, layout, key, 1)
                    else:
                        self.logger.warning("Unsupported type %s, skipping.", type_hint)

            run_button = QtW.QPushButton("Run")
            if is_togglable:
                run_button.setCheckable(True)
                run_button.toggled.connect(self._on_action_toggled)
            else:
                run_button.clicked.connect(self._on_action_requested)

            groupbox.hide()
            run_button.hide()
            if name == self.plans_combobox.currentText():
                groupbox.show()
                run_button.show()

            groupbox.setLayout(layout)
            self.groups_layout.addWidget(groupbox)
            self.button_layout.addWidget(run_button)
            self.plan_widgets[name] = PlanWidget(groupbox, run_button)

    def _on_plan_done(self) -> None:
        plan = self.plans_combobox.currentText()
        self.plan_widgets[plan].setEnabled(True)

    def _on_info_clicked(self) -> None:
        info = self.plans_info[self.plans_combobox.currentText()]
        InfoDialog.show_dialog("Plan information", info, parent=self)
