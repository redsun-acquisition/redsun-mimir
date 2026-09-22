from __future__ import annotations

from typing import TYPE_CHECKING, cast

from qtpy import QtCore, QtGui
from qtpy import QtWidgets as QtW
from redsun.log import Loggable
from redsun.path_provider import PATH_PROVIDER
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

    Lists the plans of
    [`AcquisitionPresenter`][redsun_mimir.presenter.AcquisitionPresenter],
    with their parameters and run, pause and stop controls.

    Attributes
    ----------
    sig_launch_plan_request : Signal[str, dict[str, Any]]
        Emitted when the user starts a plan, with its name and resolved
        parameters.
    sig_stop_plan_request : Signal
        Emitted when the user stops the plan.
    sig_pause_resume_request : Signal[bool]
        Emitted with ``True`` to pause, ``False`` to resume.
    sig_action_request : Signal[str, bool]
        Emitted when the user triggers an action button, with the action name
        and its toggle state.
    sig_base_dir_request : Signal[str]
        Emitted with the directory the user picked for a run to write under.
    """

    sig_launch_plan_request = Signal(str, object)
    sig_stop_plan_request = Signal()
    sig_pause_resume_request = Signal(bool)
    sig_action_request = Signal(str, bool)
    sig_base_dir_request = Signal(str)

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

        self.base_dir_label = QtW.QLineEdit(self)
        self.base_dir_label.setReadOnly(True)
        self.base_dir_label.setToolTip("Current root folder")

        self.base_dir_btn = QtW.QPushButton("Choose root...", self)
        self.base_dir_btn.setToolTip("Choose the root folder for acquired data")
        self.base_dir_btn.setFixedHeight(32)
        self.base_dir_btn.clicked.connect(self._on_base_dir_clicked)

        self.open_dir_btn = QtW.QPushButton("Browse root", self)
        self.open_dir_btn.setFixedHeight(32)
        self.open_dir_btn.setToolTip("Open the current root folder in the file manager")
        self.open_dir_btn.clicked.connect(self._on_open_dir_clicked)

        self.base_dir_layout = QtW.QHBoxLayout()
        self.base_dir_layout.addWidget(self.base_dir_btn)
        self.base_dir_layout.addWidget(self.open_dir_btn)
        self.root_layout.addWidget(self.base_dir_label)
        self.root_layout.addLayout(self.base_dir_layout)

        self.stack_widget = QtW.QStackedWidget(self)
        self.root_layout.addWidget(self.stack_widget)

        self.plan_widgets: dict[str, PlanWidget] = {}
        self._running: str | None = None

        self.plans_combobox.currentIndexChanged.connect(
            self.stack_widget.setCurrentIndex
        )
        self.setLayout(self.root_layout)

    def register_providers(self, container: VirtualContainer) -> None:
        """Register the view's signals with the container."""
        container.register_signals(self)

    def inject_dependencies(self, container: VirtualContainer) -> None:
        """Build the plan controls, and show where a run writes."""
        self.base_dir_label.setText(str(container.require(PATH_PROVIDER).base_dir))
        self.setup_ui(container.require(PLAN_SPECS))

    def _on_base_dir_clicked(self) -> None:
        """Ask for a directory, and request it as the one a run writes under."""
        chosen = QtW.QFileDialog.getExistingDirectory(
            self, "Directory for acquired data", self.base_dir_label.text()
        )
        if chosen:
            self.sig_base_dir_request.emit(chosen)

    def _on_open_dir_clicked(self) -> None:
        """Open the root folder in the system file manager."""
        QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(self.base_dir_label.text())
        )

    @slot
    def on_base_dir_changed(self, base_dir: str) -> None:
        """Show the directory a run writes under."""
        self.base_dir_label.setText(base_dir)

    def setup_ui(self, specs: set[PlanSpec]) -> None:
        """Build one control widget per plan, sorted by name."""
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

    def _current_plan(self) -> str:
        """Return the plan running, or the one selected while none runs."""
        return self._running or self.plans_combobox.currentText()

    def _mark_running(self, plan: str) -> None:
        """Hold the selector on *plan* and the root folder until it is done."""
        self._running = plan
        self.plans_combobox.setEnabled(False)
        self.base_dir_btn.setEnabled(False)

    def _on_plan_toggled(self, toggled: bool) -> None:
        plan = self._current_plan()
        plan_widget = self.plan_widgets[plan]
        plan_widget.toggle(toggled)
        if toggled:
            self._mark_running(plan)
            self.sig_launch_plan_request.emit(plan, plan_widget.parameters)
        else:
            self.sig_stop_plan_request.emit()

    def _on_plan_maybe_paused(self, paused: bool) -> None:
        self.logger.debug(f"Plan pause toggled: {paused}")
        self.plan_widgets[self._current_plan()].pause(paused)
        self.sig_pause_resume_request.emit(paused)

    def _on_plan_launch(self) -> None:
        plan = self.plans_combobox.currentText()
        plan_widget = self.plan_widgets[plan]
        plan_widget.setEnabled(False)
        plan_widget.enable_actions(False)
        self._mark_running(plan)
        self.sig_launch_plan_request.emit(plan, plan_widget.parameters)

    @slot
    def on_plan_done(self) -> None:
        """Re-enable the controls of the plan that ran, the selector and the root."""
        plan = self._current_plan()
        self._running = None
        self.plans_combobox.setEnabled(True)
        self.base_dir_btn.setEnabled(True)
        self.plan_widgets[plan].setEnabled(True)
        self.plan_widgets[plan].enable_actions(False)

    @slot
    def on_action_done(self, action_name: str) -> None:
        """Restore the button of *action_name* once its event is cleared."""
        plan_widget = self.plan_widgets[self._current_plan()]
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
        group = self.plan_widgets[self._current_plan()].actions_group
        if group:
            group.setEnabled(False)
        self.sig_action_request.emit(action_name, True)

    def _on_action_toggled(self, checked: bool, action_name: str) -> None:
        if not checked:
            plan_widget = self.plan_widgets[self._current_plan()]
            action_button = plan_widget.get_action_button(action_name)
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
