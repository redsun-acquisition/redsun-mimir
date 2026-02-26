from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from qtpy import QtCore
from qtpy import QtWidgets as QtW
from redsun.log import Loggable
from redsun.view import ViewPosition
from redsun.view.qt import QtView
from redsun.virtual import Signal

from redsun_mimir.utils import find_signals
from redsun_mimir.utils.qt import (
    InfoDialog,
    PlanWidget,
    create_plan_widget,
)

if TYPE_CHECKING:
    from redsun.virtual import VirtualContainer

    from redsun_mimir.common import PlanSpec


class AcquisitionView(QtView, Loggable):
    """View for plan selection, parameter input, and run control.

    Displays available plans from
    [`AcquisitionPresenter`][redsun_mimir.presenter.AcquisitionPresenter],
    lets the user configure parameters, and provides run/pause/stop controls.

    Parameters
    ----------
    virtual_bus :
        Reference to the virtual bus.

    Attributes
    ----------
    sigLaunchPlanRequest : Signal[str, dict[str, Any]]
        Emitted when the user starts a plan.
        Carries the plan name (``str``) and its resolved parameters
        (``dict[str, Any]``).
    sigStopPlanRequest : Signal
        Emitted when the user requests plan stop.
    sigPauseResumeRequest : Signal[bool]
        Emitted when the user toggles pause/resume.
        Carries ``True`` to pause, ``False`` to resume.
    sigActionRequest : Signal[str, bool]
        Emitted when the user triggers an action button.
        Carries the action name (``str``) and toggle state (``bool``).
    """

    sigLaunchPlanRequest = Signal(str, object)
    sigStopPlanRequest = Signal()
    sigPauseResumeRequest = Signal(bool)
    sigActionRequest = Signal(str, bool)

    @property
    def view_position(self) -> ViewPosition:
        """The position in the main view."""
        return ViewPosition.LEFT

    def __init__(
        self,
        name: str,
        /,
        **kwargs: Any,
    ) -> None:
        super().__init__(name, **kwargs)
        self.plans_info: dict[str, str] = {}

        self.root_layout = QtW.QVBoxLayout(self)

        self.top_bar_layout = QtW.QHBoxLayout()

        self.plans_combobox = QtW.QComboBox(self)
        self.plans_combobox.setToolTip("Select a plan to run")
        self.plans_combobox.setFixedHeight(32)

        self.info_btn = QtW.QPushButton(self)
        self.info_btn.setIcon(
            cast("QtW.QStyle", self.style()).standardIcon(
                QtW.QStyle.StandardPixmap.SP_FileDialogInfoView
            )
        )
        self.info_btn.setToolTip("Information about the selected plan")
        button_size = QtCore.QSize(32, 32)
        self.info_btn.setFixedSize(button_size)
        self.info_btn.setIconSize(QtCore.QSize(16, 16))
        self.info_btn.setFlat(True)
        self.info_btn.clicked.connect(self._on_info_clicked)

        self.top_bar_layout.addWidget(self.plans_combobox)
        self.top_bar_layout.addWidget(self.info_btn)
        self.root_layout.addLayout(self.top_bar_layout)

        self.stack_widget = QtW.QStackedWidget(self)
        self.root_layout.addWidget(self.stack_widget)

        self.plan_widgets: dict[str, PlanWidget] = {}

        self.plans_combobox.currentIndexChanged.connect(
            self.stack_widget.setCurrentIndex
        )
        self.setLayout(self.root_layout)

    def register_providers(self, container: VirtualContainer) -> None:
        """Register acquisition view signals in the virtual container."""
        container.register_signals(self)

    def inject_dependencies(self, container: VirtualContainer) -> None:
        """Inject plan specs from the DI container and build the UI."""
        specs: set[PlanSpec] = container.plan_specs()
        self.setup_ui(specs)
        sigs = find_signals(container, ["sigPlanDone", "sigActionDone"])
        if "sigPlanDone" in sigs:
            sigs["sigPlanDone"].connect(self._on_plan_done)
        if "sigActionDone" in sigs:
            sigs["sigActionDone"].connect(self._on_action_done, thread="main")

    def setup_ui(self, specs: set[PlanSpec]) -> None:
        """Build the UI for the acquisition plans.

        Parameters
        ----------
        specs : set[PlanSpec]
            The set of available plan specifications.
        """
        for spec in sorted(specs, key=lambda s: s.name):
            self.plans_combobox.addItem(spec.name)
            plan_widget = create_plan_widget(
                spec,
                run_callback=self._on_plan_launch,
                toggle_callback=self._on_plan_toggled,
                pause_callback=self._on_plan_maybe_paused,
                action_clicked_callback=self._on_action_clicked,
                action_toggled_callback=self._on_action_toggled,
            )
            self.stack_widget.addWidget(plan_widget.group_box)
            self.plan_widgets[spec.name] = plan_widget

        self.stack_widget.setCurrentIndex(0)

    # ------------------------------------------------------------------
    # Slot implementations
    # ------------------------------------------------------------------

    def _on_plan_toggled(self, toggled: bool) -> None:
        plan = self.plans_combobox.currentText()
        plan_widget = self.plan_widgets[plan]
        plan_widget.toggle(toggled)
        if toggled:
            self.sigLaunchPlanRequest.emit(plan, plan_widget.parameters)
        else:
            self.sigStopPlanRequest.emit()

    def _on_plan_maybe_paused(self, paused: bool) -> None:
        self.logger.debug(f"Plan pause toggled: {paused}")
        plan = self.plans_combobox.currentText()
        self.plan_widgets[plan].pause(paused)
        self.sigPauseResumeRequest.emit(paused)

    def _on_plan_launch(self) -> None:
        plan = self.plans_combobox.currentText()
        plan_widget = self.plan_widgets[plan]
        plan_widget.setEnabled(False)
        plan_widget.enable_actions(False)
        self.sigLaunchPlanRequest.emit(plan, plan_widget.parameters)

    def _on_plan_done(self) -> None:
        plan = self.plans_combobox.currentText()
        self.plan_widgets[plan].setEnabled(True)
        self.plan_widgets[plan].enable_actions(False)

    def _on_action_done(self, action_name: str) -> None:
        plan = self.plans_combobox.currentText()
        plan_widget = self.plan_widgets[plan]
        action_button = plan_widget.get_action_button(action_name)
        if action_button:
            if action_button.action.togglable:
                action_button.setEnabled(True)
                if action_button.isChecked():
                    action_button.blockSignals(True)
                    action_button.setChecked(False)
                    action_button.blockSignals(False)
            else:
                if plan_widget.actions_group:
                    plan_widget.actions_group.setEnabled(True)

    def _on_action_clicked(self, action_name: str) -> None:
        plan = self.plans_combobox.currentText()
        group = self.plan_widgets[plan].actions_group
        if group:
            group.setEnabled(False)
        self.sigActionRequest.emit(action_name, True)

    def _on_action_toggled(self, checked: bool, action_name: str) -> None:
        if not checked:
            plan = self.plans_combobox.currentText()
            action_button = self.plan_widgets[plan].get_action_button(action_name)
            if action_button:
                action_button.setEnabled(False)
        self.sigActionRequest.emit(action_name, checked)

    def _on_info_clicked(self) -> None:
        widget = self.plan_widgets[self.plans_combobox.currentText()]
        InfoDialog.show_dialog("Plan information", widget.spec.docs, parent=self)
