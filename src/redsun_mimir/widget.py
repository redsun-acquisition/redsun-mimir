from __future__ import annotations

from typing import TYPE_CHECKING

from qtpy import QtCore, QtWidgets, QtGui
from sunflare.view.qt import BaseQtWidget
from sunflare.virtual import Signal

from .config import StageModelInfo

if TYPE_CHECKING:
    from typing import Any

    from bluesky.protocols import Reading
    from event_model.documents.event_descriptor import DataKey
    from sunflare.config import RedSunSessionInfo
    from sunflare.virtual import VirtualBus


class StageWidget(BaseQtWidget):
    """Stage widget for Redsun Mimir.

    Parameters
    ----------
    config : RedSunSessionInfo
        Configuration for the session.
    virtual_bus : VirtualBus
        Virtual bus for the session.

    Attributes
    ----------
    sigMotorMove : Signal[str, str, float]
        Signal emitted when a stage is moved.
        - str: motor name
        - str: motor axis
        - float: stage new position
    sigConfigChanged : Signal[str, str, object]
        Signal emitted when a configuration value is changed.
        - str: motor name
        - str: configuration name
        - object: new configuration value

    """

    sigMotorMove = Signal(str, str, float)
    sigConfigChanged = Signal(str, str, object)

    def __init__(
        self,
        config: RedSunSessionInfo,
        virtual_bus: VirtualBus,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._config = config
        self._virtual_bus = virtual_bus
        self._description: dict[str, dict[str, DataKey]] = {}
        self._configuration: dict[str, dict[str, Reading]] = {}
        self._labels: dict[str, QtWidgets.QLabel] = {}
        self._buttons: dict[str, QtWidgets.QPushButton] = {}
        self._groups: dict[str, QtWidgets.QGroupBox] = {}
        self._line_edits: dict[str, QtWidgets.QLineEdit] = {}

        layout = QtWidgets.QGridLayout()

        self._motors_info: dict[str, StageModelInfo] = {
            name: model_info
            for name, model_info in self._config.models.items()
            if isinstance(model_info, StageModelInfo)
        }

        # row offset
        offset = 0

        # Regular expression for a valid floating-point number
        float_regex = QtCore.QRegularExpression(r"^[-+]?\d*\.?\d+$")
        self.validator = QtGui.QRegularExpressionValidator(float_regex)

        # setup the layout and connect the signals
        for name, model_info in self._motors_info.items():
            self._groups[name] = QtWidgets.QGroupBox(name)
            self._groups[name].setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)

            for i, axis in enumerate(model_info.axis):
                # create the widgets
                suffix = f"{name}:{axis}"
                self._labels["label:" + suffix] = QtWidgets.QLabel(
                    f"<strong>{axis}</strong>"
                )
                self._labels["label:" + suffix].setTextFormat(
                    QtCore.Qt.TextFormat.RichText
                )
                self._labels["pos:" + suffix] = QtWidgets.QLabel(
                    f"<strong>{0:.2f} {model_info.egu}</strong>"
                )
                self._labels["pos:" + suffix].setTextFormat(
                    QtCore.Qt.TextFormat.RichText
                )
                self._buttons["button:" + suffix + ":up"] = QtWidgets.QPushButton("+")
                self._buttons["button:" + suffix + ":down"] = QtWidgets.QPushButton("-")
                self._line_edits["edit:" + suffix] = QtWidgets.QLineEdit(
                    str(model_info.step_sizes[axis])
                )

                # setup the layout
                layout.addWidget(self._labels["label:" + suffix], offset + i, 0)
                layout.addWidget(self._labels["pos:" + suffix], offset + i, 1)
                layout.addWidget(
                    self._buttons["button:" + suffix + ":up"], offset + i, 2
                )
                layout.addWidget(
                    self._buttons["button:" + suffix + ":down"], offset + i, 3
                )
                layout.addWidget(self._line_edits["edit:" + suffix], offset + i, 4)

                # connect the signals
                self._buttons["button:" + suffix + ":up"].clicked.connect(
                    lambda _, name=name, axis=axis: self._step(name, axis, True)
                )
                self._buttons["button:" + suffix + ":down"].clicked.connect(
                    lambda _, name=name, axis=axis: self._step(name, axis, False)
                )

                self._line_edits["edit:" + suffix].textEdited.connect(
                    lambda _, name=name, axis=axis: self._validate_and_notify(
                        name, axis
                    )
                )

            offset += len(model_info.axis) + 1

        self.setLayout(layout)

    def registration_phase(self) -> None:
        """Register your signals to the virtual bus."""
        self._virtual_bus.register_signals(self)

    def connection_phase(self) -> None:
        """Connect your signals to the virtual bus.

        The controller layer will be already built when this method is called.
        We use it to directly build the GUI by retrieving a configuration of
        the currently allocated motors to create the proper widget layout.
        """
        self._virtual_bus["StageController"]["sigNewPosition"].connect(
            self._update_position
        )
        self._virtual_bus["StageController"]["sigMotorDescription"].connect(
            self._update_description
        )
        self._virtual_bus["StageController"]["sigMotorConfiguration"].connect(
            self._update_configuration
        )

    def _step(self, motor: str, axis: str, direction_up: bool) -> None:
        """Move the motor by a step size."""
        current_position = float(
            self._labels["pos:" + motor + ":" + axis].text().split()[0]
        )
        step_size = float(self._line_edits["edit:" + motor + ":" + axis].text())
        if direction_up:
            self.sigMotorMove.emit(motor, axis, current_position + step_size)
        else:
            self.sigMotorMove.emit(motor, axis, current_position - step_size)

    def _update_position(self, motor: str, position: float) -> None:
        """Update the motor position."""
        new_pos = f"<strong>{position:.2f} {self._motors_info[motor].egu}</strong>"
        self._labels["pos:" + motor].setText(new_pos)

    def _update_description(self, description: dict[str, dict[str, DataKey]]) -> None:
        """Update the motor description."""
        self._description = description

    def _update_configuration(
        self, configuration: dict[str, dict[str, Reading]]
    ) -> None:
        """Update the motor configuration."""
        self._configuration = configuration

    def _validate_and_notify(self, name: str, axis: str) -> None:
        """Validate the new step size value and notify the virtual bus when input is accepted.

        Parameters
        ----------
        name : ``str``
            Motor name.
        axis : ``str``
            Motor axis.

        """
        text = self._line_edits["edit:" + name + ":" + axis].text()
        state = self.validator.validate(text, 0)[0]
        if state == QtGui.QRegularExpressionValidator.State.Invalid:
            # set red border if input is invalid
            self._line_edits["edit:" + name + ":" + axis].setStyleSheet(
                "border: 2px solid red;"
            )
        else:
            # expression is valid
            self._line_edits["edit:" + name + ":" + axis].setStyleSheet("")

        # only notify the virtual bus if the input is valid
        if state == QtGui.QRegularExpressionValidator.State.Acceptable:
            self.sigConfigChanged.emit(name, axis, float(text))
