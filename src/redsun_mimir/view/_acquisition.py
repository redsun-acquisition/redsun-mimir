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

from redsun_mimir.common import Actions, PlanSpec
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
    """

    spec: PlanSpec
    group_box: QtW.QGroupBox
    run_button: QtW.QPushButton
    container: mgw.Container[mgw.bases.ValueWidget[Any]]
    actions_group: QtW.QGroupBox | None = None

    def toggle(self, status: bool) -> None:
        self.group_box.setEnabled(not status)
        self.run_button.setText("Stop" if status else "Run")

    def setEnabled(self, enabled: bool) -> None:
        self.group_box.setEnabled(enabled)
        self.run_button.setEnabled(enabled)

    @property
    def parameters(self) -> dict[str, Any]:
        """Key-value mapping of parameter names to their current values.

        The presenter is in charge of sorting these into args and kwargs.
        """
        return {w.name: w.value for w in self.container}


store = ino.Store.get_store("PlanManifest")


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
    sigLaunchPlanRequest : ``Signal[str, bool, dict[str, Any]]``
        Signal to launch a plan.
        - ``str``: The plan name.
        - ``bool``: Whether the plan is togglable.
        - ``dict[str, Any]``: Plan parameters.
    sigStopPlanRequest : ``Signal``
        Signal to stop a running plan.
    """

    sigLaunchPlanRequest = Signal(str, bool, object)
    sigStopPlanRequest = Signal()

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
        self.root_layout = QtW.QHBoxLayout(self)
        self.root_layout.setContentsMargins(4, 4, 4, 4)
        self.root_layout.setSpacing(4)

        # combobox to select which plan to show
        self.plans_combobox = QtW.QComboBox(self)
        self.plans_combobox.setToolTip("Select a plan to run")
        self.root_layout.addWidget(self.plans_combobox, 1)

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
        self.root_layout.addWidget(self.plans_combobox, 0)

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
        # Sort specs by name for stable ordering
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

            param_widgets: dict[str, mgw.Widget] = {}

            # Regular parameters (exclude Actions-typed params)
            for p in spec.parameters:
                if p.actions is not None or p.annotation is Actions:
                    # Don't generate parameter widgets for Actions params.
                    continue
                # Skip var-keyword (**kwargs): no sane generic widget.
                if p.is_var_keyword:
                    continue
                w = create_param_widget(p)
                param_widgets[p.name] = w

            container = mgw.Container(
                widgets=[w.native for w in param_widgets.values()]
            )
            group_layout.addRow(container.native)

            # Run button
            run_button = QtW.QPushButton("Run")
            page_layout.addWidget(run_button)

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
        # TODO: implement plan toggling logic
        ...

    def _on_plan_launch(self) -> None:
        # TODO: implement plan launch logic;
        # the event handling for start/stop
        # should maybe pass by the engine
        # to simplify things and keep things
        # consistently... maybe
        # the toggling event can be
        # added as a parameter to Actions?
        ...

    def _on_plan_done(self) -> None:
        plan = self.plans_combobox.currentText()
        self.plan_widgets[plan].setEnabled(True)

    def _on_info_clicked(self) -> None:
        widget = self.plan_widgets[self.plans_combobox.currentText()]
        InfoDialog.show_dialog("Plan information", widget.spec.docs, parent=self)
