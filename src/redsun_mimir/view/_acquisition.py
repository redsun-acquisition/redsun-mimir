from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import magicgui.widgets as mgw
from qtpy import QtCore
from qtpy import QtWidgets as QtW
from redsun.config import ViewPositionTypes
from sunflare.log import Loggable
from sunflare.view.qt import QtView
from sunflare.virtual import Signal

from redsun_mimir.actions import Action
from redsun_mimir.common import PlanSpec  # noqa: TC001
from redsun_mimir.utils.qt import InfoDialog, create_param_widget

if TYPE_CHECKING:
    from typing import Any

    from dependency_injector.containers import DynamicContainer
    from sunflare.virtual import VirtualBus


class ActionButton(QtW.QPushButton):
    """A QPushButton subclass that encapsulates Action metadata.

    This button automatically updates its text based on the toggle state
    using the action's toggle_states attribute.

    Parameters
    ----------
    action : ``Action``
        The action metadata to associate with this button.
    parent : ``QtWidgets.QWidget | None``, optional
        The parent widget. Default is None.

    Attributes
    ----------
    action : ``Action``
        The action metadata associated with this button.
    """

    def __init__(self, action: Action, parent: QtW.QWidget | None = None) -> None:
        self.name_capital = action.name.capitalize()
        super().__init__(self.name_capital, parent)
        self.action = action

        if action.description:
            self.setToolTip(action.description)

        if action.togglable:
            self.setCheckable(True)
            self.toggled.connect(self._update_text)
            # initialize text based on default state (unchecked)
            self._update_text(False)

    def _update_text(self, checked: bool) -> None:
        """Update button text based on toggle state."""
        state_text = (
            self.action.toggle_states[1] if checked else self.action.toggle_states[0]
        )
        self.setText(f"{self.name_capital} ({state_text})")


@dataclass(frozen=True)
class PlanWidget:
    """
    Container for of a plan-binded widget.

    Parameters
    ----------
    spec : ``PlanSpec``
        The plan specification.
    group_box : ``QtWidgets.QGroupBox``
        The group box containing the plan UI.
    run_button : ``QtWidgets.QPushButton``
        The button to run the plan.
    container : ``magicgui.widgets.Container[Any]``
        The container holding the parameter widgets.
    action_buttons : ``dict[str, ActionButton]``
        Mapping of action names to their buttons for direct access.
    actions_group : ``QtWidgets.QGroupBox | None``
        The group box containing action buttons (for group-level enable/disable).
    pause_button : ``QtWidgets.QPushButton | None``
        The button to pause the plan (if applicable).
    """

    spec: PlanSpec
    group_box: QtW.QGroupBox
    run_button: QtW.QPushButton
    container: mgw.Container[mgw.bases.ValueWidget[Any]]
    action_buttons: dict[str, ActionButton]
    actions_group: QtW.QGroupBox | None = None
    pause_button: QtW.QPushButton | None = None

    def toggle(self, status: bool) -> None:
        """Toggle the run button state and enable/disable pause button."""
        self.run_button.setText("Stop" if status else "Run")
        if self.pause_button:
            self.pause_button.setEnabled(status)
        # Enable/disable actions group when plan is toggled
        if self.actions_group:
            self.actions_group.setEnabled(status)
        # Disable parameter widgets when plan is running
        self.container.enabled = not status

    def pause(self, status: bool) -> None:
        """Toggle the pause button state and enable/disable run button."""
        if self.pause_button:
            self.pause_button.setText("Resume" if status else "Pause")
            self.run_button.setEnabled(not status)

    def setEnabled(self, enabled: bool) -> None:
        """Enable or disable the entire plan widget."""
        self.group_box.setEnabled(enabled)
        self.run_button.setEnabled(enabled)
        # Explicitly enable/disable parameter widgets
        self.container.enabled = enabled

    def enable_actions(self, enabled: bool = True) -> None:
        """Enable or disable all action buttons as a group."""
        if self.actions_group:
            self.actions_group.setEnabled(enabled)

    def get_action_button(self, action_name: str) -> ActionButton | None:
        """Get a specific action button by name.

        Parameters
        ----------
        action_name : ``str``
            The name of the action.

        Returns
        -------
        ``ActionButton | None``
            The action button if found, None otherwise.
        """
        return self.action_buttons.get(action_name)

    def has_actions(self) -> bool:
        """Check if this plan has any action buttons."""
        return bool(self.action_buttons)

    @property
    def parameters(self) -> dict[str, Any]:
        """Key-value mapping of parameter names to their current values.

        The presenter is in charge of sorting these into args and kwargs.
        """
        return {w.name: w.value for w in self.container}


class AcquisitionWidget(QtView, Loggable):
    """Widget for the acquisition settings.

    Parameters
    ----------
    virtual_bus : ``VirtualBus``
        Reference to the virtual bus.

    Attributes
    ----------
    sigLaunchPlanRequest : ``Signal[str, dict[str, Any]]``
        Signal to launch a plan.
        - ``str``: The plan name.
        - ``dict[str, Any]``: Plan parameters.
    sigStopPlanRequest : ``Signal``
        Signal to stop the currently running plan.
    sigPauseResumeRequest : ``Signal[bool]``
        Signal to pause or resume the currently running plan.
    """

    sigLaunchPlanRequest = Signal(str, object)
    sigStopPlanRequest = Signal()
    sigPauseResumeRequest = Signal(bool)
    sigActionRequest = Signal(str, bool)

    position = ViewPositionTypes.CENTER

    def __init__(
        self,
        virtual_bus: VirtualBus,
        /,
        **kwargs: Any,
    ):
        super().__init__(virtual_bus, **kwargs)
        self.plans_info: dict[str, str] = {}

        # root layout
        self.root_layout = QtW.QVBoxLayout(self)

        # combobox and info button layout
        self.top_bar_layout = QtW.QHBoxLayout()

        # combobox to select which plan to show
        self.plans_combobox = QtW.QComboBox(self)
        self.plans_combobox.setToolTip("Select a plan to run")
        self.plans_combobox.setFixedHeight(32)

        # info button to open a dialog with plan docstring
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

        # add widgets to the horizontal layout
        self.top_bar_layout.addWidget(self.plans_combobox)
        self.top_bar_layout.addWidget(self.info_btn)

        # put the top bar into the main vertical layout
        self.root_layout.addLayout(self.top_bar_layout)

        # stacked widget: one page per plan (each page is a param form);
        # only used for visualization, not for logic
        self.stack_widget = QtW.QStackedWidget(self)
        self.root_layout.addWidget(self.stack_widget)

        # plan name to PlanWidget mapping
        self.plan_widgets: dict[str, PlanWidget] = {}

        self.plans_combobox.currentIndexChanged.connect(
            self.stack_widget.setCurrentIndex
        )
        self.setLayout(self.root_layout)
        self.plans_actions_buttons: dict[str, dict[str, ActionButton]] = {}

    def inject_dependencies(self, container: DynamicContainer) -> None:
        """Inject plan specs from the DI container and build the UI."""
        specs: set[PlanSpec] = container.plan_specs()  # type: ignore[attr-defined]
        self.setup_ui(specs)

    def setup_ui(self, specs: set[PlanSpec]) -> None:
        """
        Build the UI for the acquisition plans.

        This is called via injection, to ensure that the
        plan specifications are available from the store.

        Parameters
        ----------
        specs : ``set[PlanSpec]``
            The set of available plan specifications.
        """
        # sort specs by name for stable ordering
        for spec in sorted(specs, key=lambda s: s.name):
            func_name = spec.name
            self.plans_combobox.addItem(func_name)

            page = QtW.QWidget()
            page_layout = QtW.QVBoxLayout(page)
            page_layout.setContentsMargins(4, 4, 4, 4)
            page_layout.setSpacing(4)

            # Group box for regular parameters
            group_box = QtW.QGroupBox("Parameters")
            group_layout = QtW.QFormLayout(group_box)
            page_layout.addWidget(group_box)

            param_widgets: dict[str, mgw.bases.ValueWidget[Any]] = {}

            # Regular parameters (exclude Action-typed params)
            for p in spec.parameters:
                if p.hidden:
                    # do nothing
                    continue
                if p.actions is not None:
                    # Don't generate parameter widgets for Action params.
                    continue
                # Skip var-keyword (**kwargs): no sane generic widget yet.
                if p.kind.name == "VAR_KEYWORD":
                    continue
                w = create_param_widget(p)
                param_widgets[p.name] = cast("mgw.bases.ValueWidget[Any]", w)

            container = mgw.Container(
                widgets=[w for w in param_widgets.values()],
            )
            native_container: QtW.QWidget = container.native
            native_container.adjustSize()
            group_layout.addRow(container.native)

            run_layout = QtW.QHBoxLayout()
            run_container = QtW.QWidget(self)

            # run button
            run_button = QtW.QPushButton("Run")
            if spec.togglable:
                run_button.setCheckable(True)
                run_button.toggled.connect(self._on_plan_toggled)
            else:
                run_button.clicked.connect(self._on_plan_launch)
            run_layout.addWidget(run_button)

            # we can't pause if we can't toggle
            pause_button: QtW.QPushButton | None = None
            if spec.togglable and spec.pausable:
                pause_button = QtW.QPushButton("Pause")
                pause_button.setEnabled(False)
                pause_button.setCheckable(True)
                pause_button.toggled.connect(self._on_plan_maybe_paused)
                run_layout.addWidget(pause_button)
            run_container.setLayout(run_layout)
            page_layout.addWidget(run_container)

            actions_group_box: QtW.QGroupBox | None = None
            actions_params = [p for p in spec.parameters if p.actions is not None]

            action_buttons: dict[str, ActionButton] = {}
            if actions_params:
                self.plans_actions_buttons[func_name] = {}
                actions_group_box = QtW.QGroupBox("Actions")
                actions_layout = QtW.QHBoxLayout(actions_group_box)

                # initially actions are disabled; they can be
                # enabled when the plan is running
                actions_group_box.setEnabled(False)
                for p in actions_params:
                    actions_meta = p.actions
                    if actions_meta is None:
                        continue
                    # Handle both single Action and Sequence[Action]
                    action_list = (
                        [actions_meta]
                        if isinstance(actions_meta, Action)
                        else actions_meta
                    )
                    for action in action_list:
                        btn = ActionButton(action)
                        if action.togglable:
                            btn.toggled.connect(
                                lambda checked, name=action.name: (
                                    self._on_action_toggled(checked, name)
                                )
                            )
                        else:
                            btn.clicked.connect(
                                lambda _, name=action.name: self._on_action_clicked(
                                    name
                                )
                            )
                        self.plans_actions_buttons[func_name][action.name] = btn
                        action_buttons[action.name] = btn
                        actions_layout.addWidget(btn)
                page_layout.addWidget(actions_group_box)
            self.stack_widget.addWidget(page)
            self.plan_widgets[func_name] = PlanWidget(
                spec=spec,
                group_box=group_box,
                run_button=run_button,
                pause_button=pause_button,
                container=container,
                actions_group=actions_group_box,
                action_buttons=action_buttons,
            )

        self.stack_widget.setCurrentIndex(0)

    def connect_to_virtual(self) -> None:
        """Register signals and connect to virtual bus."""
        self.virtual_bus.register_signals(self)
        self.virtual_bus.signals["AcquisitionController"]["sigPlanDone"].connect(
            self._on_plan_done
        )
        self.virtual_bus.signals["AcquisitionController"]["sigActionDone"].connect(
            self._on_action_done, thread="main"
        )

    def _on_plan_toggled(self, toggled: bool) -> None:
        plan = self.plans_combobox.currentText()
        plan_widget = self.plan_widgets[plan]
        plan_widget.toggle(toggled)
        if toggled:
            parameters = plan_widget.parameters
            self.sigLaunchPlanRequest.emit(plan, parameters)
        else:
            self.sigStopPlanRequest.emit()

    def _on_plan_maybe_paused(self, paused: bool) -> None:
        self.logger.debug(f"Plan pause toggled: {paused}")
        plan = self.plans_combobox.currentText()
        self.plan_widgets[plan].pause(paused)
        self.sigPauseResumeRequest.emit(paused)

    def _on_plan_launch(self) -> None:
        plan = self.plans_combobox.currentText()
        parameters = self.plan_widgets[plan].parameters
        self.plan_widgets[plan].setEnabled(False)
        self.plan_widgets[plan].enable_actions(False)
        self.sigLaunchPlanRequest.emit(plan, parameters)

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
                # Re-enable the button (in case it was disabled during processing)
                action_button.setEnabled(True)

                # If currently checked, uncheck it
                if action_button.isChecked():
                    # Block signals temporarily to avoid triggering the toggled callback
                    action_button.blockSignals(True)
                    action_button.setChecked(False)
                    action_button.blockSignals(False)
            else:
                # For non-togglable actions, re-enable the entire actions group
                if plan_widget.actions_group:
                    plan_widget.actions_group.setEnabled(True)

    def _on_action_clicked(self, action_name: str) -> None:
        plan = self.plans_combobox.currentText()
        group = self.plan_widgets[plan].actions_group
        if group:
            group.setEnabled(False)
        self.sigActionRequest.emit(action_name, True)

    def _on_action_toggled(self, checked: bool, action_name: str) -> None:
        # If unchecking (stopping a write_forever operation), disable the button
        # to prevent accidental clicks during completion/cleanup
        if not checked:
            plan = self.plans_combobox.currentText()
            plan_widget = self.plan_widgets[plan]
            action_button = plan_widget.get_action_button(action_name)
            if action_button:
                action_button.setEnabled(False)

        self.sigActionRequest.emit(action_name, checked)

    def _on_info_clicked(self) -> None:
        widget = self.plan_widgets[self.plans_combobox.currentText()]
        InfoDialog.show_dialog("Plan information", widget.spec.docs, parent=self)
