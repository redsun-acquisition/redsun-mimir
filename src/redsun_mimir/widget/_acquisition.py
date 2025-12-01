from __future__ import annotations

import inspect
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import in_n_out as ino
import magicgui.widgets as mw
from magicgui import register_type
from qtpy import QtCore
from qtpy import QtWidgets as QtW
from sunflare.log import Loggable
from sunflare.model import ModelProtocol
from sunflare.view.qt import BaseQtWidget
from sunflare.virtual import Signal

from redsun_mimir.common import PlanManifest  # noqa: TC001
from redsun_mimir.utils.qt import InfoDialog

if TYPE_CHECKING:
    from typing import Any

    from sunflare.config import ViewInfoProtocol
    from sunflare.virtual import VirtualBus


@dataclass(frozen=True)
class PlanWidget:
    """Helper dataclass to hold plan UI information."""

    group: QtW.QGroupBox
    run: QtW.QPushButton
    container: mw.Container[Any]
    togglable: bool

    def toggle(self, status: bool) -> None:
        if status:
            self.group.setEnabled(False)
            self.run.setText("Stop")
        else:
            self.group.setEnabled(True)
            self.run.setText("Run")

    def setEnabled(self, enabled: bool) -> None:
        self.group.setEnabled(enabled)
        self.run.setEnabled(enabled)

    def hide(self) -> None:
        self.group.hide()
        self.run.hide()

    def show(self) -> None:
        self.group.show()
        self.run.show()

    @property
    def parameters(self) -> dict[str, Any]:
        params: dict[str, Any] = {}
        for i in range(len(self.container)):
            w: mw.bases.ValueWidget[Any] = self.container[i]
            if isinstance(w.annotation, ModelProtocol):
                # store the annotation and the current
                # selected choices in a tuple
                params[w.name] = (w.annotation, w.value)
            else:
                params[w.name] = w.value
        return params


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

        ino.Store.get_store("PlanManifest").inject(self.setup_ui)()

    def setup_ui(self, manifests: set[PlanManifest]) -> None:
        """Initialize the UI with the provided plan manifests.

        Widgets are created via `magicgui`, based on the
        plan manifest information.

        Parameters
        ----------
        manifests : set[PlanManifest]
            Set of plan manifests to populate the UI with.
            Injected from `AcquisitionController`.
        """
        for manifest in manifests:
            self.plans_combobox.addItem(manifest.name)
            self.plans_info[manifest.name] = manifest.description
            layout = QtW.QVBoxLayout()
            groupbox = QtW.QGroupBox(parent=self)
            widgets: list[mw.Widget] = []
            events_param = manifest.parameters.get("events", None)
            if events_param and events_param.kind == inspect.Parameter.KEYWORD_ONLY:
                # TODO: understand why mypy says this is unreachable
                if isinstance(events_param.origin, Sequence) and isinstance(
                    events_param.annotation, str
                ):  # type: ignore[unreachable]
                    # TODO: what to do here?
                    ...
            for pname, param in manifest.parameters.items():
                options: dict[str, Any] = {}
                default = param.default
                if param.meta:
                    if param.meta.exclude:
                        # skip excluded parameters
                        continue
                    if param.meta.min is not None:
                        options["min"] = param.meta.min
                    if param.meta.max is not None:
                        options["max"] = param.meta.max
                # TODO: understand why mypy says this is unreachable
                if isinstance(param.origin, Sequence) and isinstance(
                    param.annotation, ModelProtocol
                ):  # type: ignore[unreachable]
                    register_type(param.annotation, widget_type=mw.Select)  # type: ignore[unreachable]
                    options["choices"] = param.choices
                    default = param.choices[0] if param.choices else default
                widget = mw.create_widget(
                    name=pname,
                    value=default,
                    annotation=param.annotation,
                    param_kind=param.kind,
                    options=options,
                )
                widgets.append(widget)
            container = mw.Container(
                widgets=widgets,
            )
            run_button = QtW.QPushButton("Run")
            if manifest.is_toggleable:
                run_button.setCheckable(True)
                run_button.toggled.connect(self._on_plan_toggled)
            else:
                run_button.clicked.connect(self._on_plan_launch)

            groupbox.hide()
            run_button.hide()
            if manifest.name == self.plans_combobox.currentText():
                groupbox.show()
                run_button.show()

            layout.addWidget(container.native)
            groupbox.setLayout(layout)
            self.groups_layout.addWidget(groupbox)
            self.button_layout.addWidget(run_button)
            self.plan_widgets[manifest.name] = PlanWidget(
                group=groupbox,
                run=run_button,
                container=container,
                togglable=manifest.is_toggleable,
            )

    def _on_plan_changed(self, text: str) -> None:
        for name, widget in self.plan_widgets.items():
            if name == text:
                widget.show()
            else:
                widget.hide()
        self.adjustSize()

    def registration_phase(self) -> None:
        self.virtual_bus.register_signals(self)

    def connection_phase(self) -> None: ...

    def _on_plan_toggled(self, toggled: bool) -> None:
        """Toggle the execution of a plan.

        Parameters
        ----------
        toggled : bool
            Whether the plan is now toggled on or off.
        """
        plan = self.plans_combobox.currentText()
        self.plan_widgets[plan].toggle(toggled)
        if toggled:
            togglable, parameters = (
                self.plan_widgets[plan].togglable,
                self.plan_widgets[plan].parameters,
            )
            self.logger.debug(f"Launching {plan}")
            self.logger.debug(f"Parameters: {parameters}")
            self.sigLaunchPlanRequest.emit(plan, togglable, parameters)
        else:
            self.sigStopPlanRequest.emit()
            self.plan_widgets[plan].setEnabled(True)

    def _on_plan_launch(self) -> None:
        plan = self.plans_combobox.currentText()
        togglable, parameters = (
            self.plan_widgets[plan].togglable,
            self.plan_widgets[plan].parameters,
        )
        self.logger.debug(f"Launching {plan}")
        self.logger.debug(f"Parameters: {parameters}")
        self.sigLaunchPlanRequest.emit(plan, togglable, parameters)

    def _on_plan_done(self) -> None:
        plan = self.plans_combobox.currentText()
        self.plan_widgets[plan].setEnabled(True)

    def _on_info_clicked(self) -> None:
        info = self.plans_info[self.plans_combobox.currentText()]
        InfoDialog.show_dialog("Plan information", info, parent=self)
