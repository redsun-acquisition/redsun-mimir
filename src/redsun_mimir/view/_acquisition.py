from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import in_n_out as ino
import magicgui.widgets as mgw
from qtpy import QtCore
from qtpy import QtWidgets as QtW
from sunflare.log import Loggable
from sunflare.view.qt import BaseQtWidget
from sunflare.virtual import Signal

from redsun_mimir.common import PlanSpec  # noqa: TC001
from redsun_mimir.common.actions import Actions
from redsun_mimir.utils.qt import InfoDialog, create_param_widget

if TYPE_CHECKING:
    from typing import Any

    from sunflare.config import ViewInfoProtocol
    from sunflare.virtual import VirtualBus


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
    pause_button : ``QtWidgets.QPushButton | None``
        The button to pause the plan (if applicable).
    """

    spec: PlanSpec
    group_box: QtW.QGroupBox
    run_button: QtW.QPushButton
    container: mgw.Container[mgw.bases.ValueWidget[Any]]
    actions_group: QtW.QGroupBox | None = None
    pause_button: QtW.QPushButton | None = None

    def toggle(self, status: bool) -> None:
        self.run_button.setText("Stop" if status else "Run")

    def pause(self, status: bool) -> None:
        if self.pause_button:
            self.pause_button.setText("Resume" if status else "Pause")
            self.run_button.setEnabled(not status)

    def setEnabled(self, enabled: bool) -> None:
        self.group_box.setEnabled(enabled)
        self.run_button.setEnabled(enabled)

    @property
    def parameters(self) -> dict[str, Any]:
        """Key-value mapping of parameter names to their current values.

        The presenter is in charge of sorting these into args and kwargs.
        """
        return {w.name: w.value for w in self.container}


store = ino.Store.get_store("plan_specs")


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

    def __init__(
        self,
        view_info: ViewInfoProtocol,
        virtual_bus: VirtualBus,
        *args: Any,
        **kwargs: Any,
    ):
        super().__init__(view_info, virtual_bus, *args, **kwargs)
        self.plans_info: dict[str, str] = {}

        # root layout
        self.root_layout = QtW.QVBoxLayout(self)
        self.root_layout.setContentsMargins(4, 4, 4, 4)
        self.root_layout.setSpacing(4)

        # combobox and info button layout
        self.top_bar_layout = QtW.QHBoxLayout()
        self.top_bar_layout.setContentsMargins(0, 0, 0, 0)
        self.top_bar_layout.setSpacing(4)

        # combobox to select which plan to show
        self.plans_combobox = QtW.QComboBox(self)
        self.plans_combobox.setToolTip("Select a plan to run")

        # info button to open a dialog with plan docstring
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

        # add widgets to the horizontal layout
        self.top_bar_layout.addWidget(self.plans_combobox, 1)  # stretch = 1 (expands)
        self.top_bar_layout.addWidget(self.info_btn, 0)  # fixed width

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

        ino.Store.get_store("plan_specs").inject(self.setup_ui)()

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

            # Regular parameters (exclude Actions-typed params)
            for p in spec.parameters:
                if p.hidden:
                    # do nothing
                    continue
                if p.actions is not None or p.annotation is Actions:
                    # Don't generate parameter widgets for Actions params.
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

            # Run button
            run_button = QtW.QPushButton("Run")
            if spec.togglable:
                run_button.setCheckable(True)
                run_button.toggled.connect(self._on_plan_toggled)
            else:
                run_button.clicked.connect(self._on_plan_launch)
            run_layout.addWidget(run_button)
            if spec.pausable:
                pause_button = QtW.QPushButton("Pause")
                # No wiring for now; user can extend this.
                run_layout.addWidget(pause_button)
            run_container.setLayout(run_layout)
            page_layout.addWidget(run_container)

            # Actions group (for parameters typed as Actions with a default)
            actions_group_box: QtW.QGroupBox | None = None
            actions_params = [p for p in spec.parameters if p.actions is not None]

            if actions_params:
                actions_group_box = QtW.QGroupBox("Actions")
                actions_layout = QtW.QHBoxLayout(actions_group_box)

                for p in actions_params:
                    act = p.actions
                    if act is None:
                        continue
                    for name_str in act.names:
                        btn = QtW.QPushButton(str(name_str))
                        # No wiring for now; user can extend this.
                        actions_layout.addWidget(btn)

                page_layout.addWidget(actions_group_box)

            self.stack_widget.addWidget(page)
            self.plan_widgets[func_name] = PlanWidget(
                spec=spec,
                group_box=group_box,
                run_button=run_button,
                container=container,
                actions_group=actions_group_box,
            )

        self.stack_widget.setCurrentIndex(0)

    def registration_phase(self) -> None:
        self.virtual_bus.register_signals(self)

    def connection_phase(self) -> None: ...

    def _on_plan_toggled(self, toggled: bool) -> None:
        plan = self.plans_combobox.currentText()
        if toggled:
            parameters = self.plan_widgets[plan].parameters
            self.sigLaunchPlanRequest.emit(plan, parameters)
        else:
            self.sigStopPlanRequest.emit()
        self.plan_widgets[plan].toggle(toggled)

    def _on_plan_maybe_paused(self, paused: bool) -> None:
        plan = self.plans_combobox.currentText()
        self.plan_widgets[plan].pause(paused)
        self.sigPauseResumeRequest.emit(paused)

    def _on_plan_launch(self) -> None:
        plan = self.plans_combobox.currentText()
        parameters = self.plan_widgets[plan].parameters
        self.sigLaunchPlanRequest.emit(plan, parameters)

    def _on_plan_done(self) -> None:
        plan = self.plans_combobox.currentText()
        self.plan_widgets[plan].setEnabled(True)

    def _on_info_clicked(self) -> None:
        widget = self.plan_widgets[self.plans_combobox.currentText()]
        InfoDialog.show_dialog("Plan information", widget.spec.docs, parent=self)
