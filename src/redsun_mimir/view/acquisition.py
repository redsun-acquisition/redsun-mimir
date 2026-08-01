from __future__ import annotations

from typing import TYPE_CHECKING, cast

from qtpy import QtCore
from qtpy import QtWidgets as QtW
from redsun.log import Loggable
from redsun.view import ViewPosition
from redsun.view.qt import QtView
from redsun.view.qt.utils import PlanInfoDialog, PlanWidget, create_plan_widget
from redsun.virtual import Signal, slot

from redsun_mimir.providers import PLAN_SPECS

if TYPE_CHECKING:
    from redsun.presenter.plan_spec import PlanSpec
    from redsun.virtual import VirtualContainer


class AcquisitionView(QtView, Loggable):
    """View for plan selection, parameter input, and run control.

    Displays available plans from
    [`AcquisitionPresenter`][redsun_mimir.presenter.AcquisitionPresenter],
    lets the user configure parameters, and provides run/pause/stop controls.

    Parameters
    ----------
    name : str
        Identity key of the view.

    Attributes
    ----------
    sig_launch_plan_request : Signal[str, dict[str, Any]]
        Emitted when the user starts a plan.
        Carries the plan name (``str``) and its resolved parameters
        (``dict[str, Any]``).
    sig_stop_plan_request : Signal
        Emitted when the user requests plan stop.
    sig_pause_resume_request : Signal[bool]
        Emitted when the user toggles pause/resume.
        Carries ``True`` to pause, ``False`` to resume.
    sig_action_request : Signal[str, bool]
        Emitted when the user triggers an action button.
        Carries the action name (``str``) and toggle state (``bool``).
    """

    sig_launch_plan_request = Signal(str, object)
    sig_stop_plan_request = Signal()
    sig_pause_resume_request = Signal(bool)
    sig_action_request = Signal(str, bool)

    @property
    def view_position(self) -> ViewPosition:
        """The position in the main view."""
        return ViewPosition.LEFT

    def __init__(
        self,
        name: str,
        /,
    ) -> None:
        super().__init__(name)
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
        """Build the plan controls from the acquisition presenter's specs."""
        self.setup_ui(container.require(PLAN_SPECS))

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
            self._wire_device_validation(plan_widget)

        self.stack_widget.setCurrentIndex(0)

    def _on_plan_toggled(self, toggled: bool) -> None:
        plan = self.plans_combobox.currentText()
        plan_widget = self.plan_widgets[plan]
        plan_widget.toggle(toggled)
        if toggled:
            self.sig_launch_plan_request.emit(plan, plan_widget.parameters)
        else:
            self.sig_stop_plan_request.emit()

    def _on_plan_maybe_paused(self, paused: bool) -> None:
        self.logger.debug(f"Plan pause toggled: {paused}")
        plan = self.plans_combobox.currentText()
        self.plan_widgets[plan].pause(paused)
        self.sig_pause_resume_request.emit(paused)

    def _on_plan_launch(self) -> None:
        plan = self.plans_combobox.currentText()
        plan_widget = self.plan_widgets[plan]
        plan_widget.setEnabled(False)
        plan_widget.enable_actions(False)
        self.sig_launch_plan_request.emit(plan, plan_widget.parameters)

    @slot
    def on_plan_done(self) -> None:
        """Re-enable the current plan's controls now that the run finished."""
        plan = self.plans_combobox.currentText()
        self.plan_widgets[plan].setEnabled(True)
        self.plan_widgets[plan].enable_actions(False)

    @slot
    def on_action_done(self, action_name: str) -> None:
        """Restore the button of *action_name* once its event is cleared."""
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
        self.sig_action_request.emit(action_name, True)

    def _on_action_toggled(self, checked: bool, action_name: str) -> None:
        if not checked:
            plan = self.plans_combobox.currentText()
            action_button = self.plan_widgets[plan].get_action_button(action_name)
            if action_button:
                action_button.setEnabled(False)
        self.sig_action_request.emit(action_name, checked)

    def _wire_device_validation(self, plan_widget: PlanWidget) -> None:
        """Disable Run if any DeviceSequenceEdit has an empty selection."""
        for w in plan_widget.device_widgets:
            w.changed.connect(
                lambda _val, pw=plan_widget: self._on_device_selection_changed(pw)
            )
        self._on_device_selection_changed(plan_widget)

    def _on_device_selection_changed(self, plan_widget: PlanWidget) -> None:
        """Disable Run while any device sequence widget has no selection."""
        any_empty = any(
            isinstance(w.get_value(), list) and len(w.get_value()) == 0
            for w in plan_widget.device_widgets
        )
        plan_widget.run_button.setEnabled(not any_empty)

    def _on_info_clicked(self) -> None:
        widget = self.plan_widgets[self.plans_combobox.currentText()]
        PlanInfoDialog.show_dialog("Plan information", widget.spec.docs, parent=self)
