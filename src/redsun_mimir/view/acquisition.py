from __future__ import annotations

from collections.abc import Mapping  # noqa: TC003
from typing import TYPE_CHECKING

from psygnal import Signal
from qtpy import QtCore, QtGui
from qtpy import QtWidgets as QtW
from redsun import CallbackType, DeviceMapping, HasPlans, Placement, slot
from redsun.engine.actions import ActionState
from redsun.log import Loggable
from redsun.path_provider import SessionPathProvider  # noqa: TC002
from redsun.presenter.plan_spec import UnresolvableAnnotationError, create_plan_spec
from redsun.qt import Dock
from redsun.view.qt.utils import PlanInfoDialog, PlanWidget, create_plan_widget

if TYPE_CHECKING:
    from pathlib import Path

    from redsun import PlanEntry
    from redsun.engine import ProgressState
    from redsun.view.qt.utils import ActionButton


class AcquisitionView(QtW.QWidget, Loggable):
    """View for plan selection, parameter input, and run control.

    Lists every plan of the session, chosen from a list, with its
    parameters, the document callbacks to run it with, and run, pause and
    stop controls.
    """

    placement: Placement = Dock("left")

    sig_launch_plan_request = Signal(str, object, object)
    """Emitted when the user starts a plan, with its name, its parameter
    values and the names of the callbacks the user attached to it."""

    sig_stop_plan_request = Signal()
    """Emitted when the user stops the plan."""

    sig_pause_resume_request = Signal(bool)
    """Emitted with `True` to pause, `False` to resume."""

    sig_action_request = Signal(str, bool)
    """Emitted when the user presses an action button, with the action name
    and whether the button is pressed."""

    sig_base_dir_request = Signal(str)
    """Emitted with the directory the user picked for a run to write under."""

    def __init__(self, name: str, parent: QtW.QWidget) -> None:
        super().__init__(parent)
        self.name = name

        self.root_layout = QtW.QVBoxLayout(self)

        self.top_bar_layout = QtW.QHBoxLayout()

        self.plans_combobox = QtW.QComboBox(self)
        self.plans_combobox.setToolTip("Select a plan to run")
        self.plans_combobox.setFixedHeight(32)

        self.info_btn = QtW.QPushButton(self)
        # PyQt6 types style() as optional, PySide6 does not
        style = self.style()
        assert style is not None
        self.info_btn.setIcon(
            style.standardIcon(QtW.QStyle.StandardPixmap.SP_FileDialogInfoView)
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

    def setup(
        self,
        providers: Mapping[str, HasPlans],
        callbacks: Mapping[str, CallbackType],
        devices: DeviceMapping,
        paths: SessionPathProvider,
    ) -> None:
        """Build one control widget per plan, and show where a run writes.

        A plan whose signature no plan widget can show is logged and left out.
        Every callback a plan does not list starts attached to it.
        """
        self.base_dir_label.setText(str(paths.base_dir))
        entries: dict[str, PlanEntry] = {}
        for component in providers.values():
            entries.update(component.plan_map())
        for plan_name in sorted(entries):
            entry = entries[plan_name]
            try:
                spec = create_plan_spec(entry["plan"], devices)
            except (UnresolvableAnnotationError, ValueError) as error:
                self.logger.warning(str(error))
                continue
            self.plans_combobox.addItem(plan_name)
            plan_widget = create_plan_widget(
                spec,
                toggle_callback=self._on_plan_toggled,
                pause_callback=self._on_plan_maybe_paused,
                action_clicked_callback=self._on_action_clicked,
                action_toggled_callback=self._on_action_toggled,
                plan_callbacks=entry.get("callbacks", ()),
                available_callbacks=callbacks,
                attached_callbacks=None,
            )
            self.stack_widget.addWidget(plan_widget.group_box)
            self.plan_widgets[plan_name] = plan_widget
            self._wire_device_validation(plan_widget)

        self.stack_widget.setCurrentIndex(0)

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
    def on_base_dir_changed(self, base_dir: Path) -> None:
        """Show the directory a run writes under."""
        self.base_dir_label.setText(str(base_dir))

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
            self.sig_launch_plan_request.emit(
                plan, plan_widget.parameters, plan_widget.attached_callbacks
            )
        else:
            self.sig_stop_plan_request.emit()

    def _on_plan_maybe_paused(self, paused: bool) -> None:
        self.logger.debug(f"Plan pause toggled: {paused}")
        self.plan_widgets[self._current_plan()].pause(paused)
        self.sig_pause_resume_request.emit(paused)

    @slot
    def on_progress(self, scopes: tuple[ProgressState, ...]) -> None:
        """Show the progress scopes of the running plan on its page."""
        self.plan_widgets[self._current_plan()].show_progress(scopes)

    @slot
    def on_plan_done(self) -> None:
        """Show the plan that ran as stopped, and free the selector and the root."""
        plan = self._current_plan()
        self._running = None
        self.plans_combobox.setEnabled(True)
        self.base_dir_btn.setEnabled(True)
        self.plan_widgets[plan].toggle(False)
        self.plan_widgets[plan].setEnabled(True)

    @slot
    def on_action_changed(self, name: str, state: str) -> None:
        """Set the button of the action *name* of the current plan to *state*.

        Disabled and released when idle, enabled when offered, and kept
        enabled while running only if it is a toggle, so it can be released.
        """
        button = self.plan_widgets[self._current_plan()].get_action_button(name)
        if button is not None:
            self._set_action_button(button, state)

    def _set_action_button(self, button: ActionButton, state: str) -> None:
        match state:
            case ActionState.IDLE:
                button.setEnabled(False)
                button.release()
            case ActionState.OFFERED:
                button.setEnabled(True)
            case ActionState.RUNNING:
                button.setEnabled(button.isCheckable())

    def _on_action_clicked(self, action_name: str) -> None:
        self.sig_action_request.emit(action_name, True)

    def _on_action_toggled(self, checked: bool, action_name: str) -> None:
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
