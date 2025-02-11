from __future__ import annotations

from typing import TYPE_CHECKING

from qtpy import QtCore, QtWidgets
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

    """

    sigMotorMove = Signal(str, str, float)
    sigGetDescription = Signal()

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
        self._text_edits: dict[str, QtWidgets.QLineEdit] = {}

        layout = QtWidgets.QGridLayout()

        self._motors_info: dict[str, StageModelInfo] = {
            name: model_info
            for name, model_info in self._config.models.items()
            if isinstance(model_info, StageModelInfo)
        }
        offset = 0

        # setup the layout and connect the signals
        for name, model_info in self._motors_info.items():
            for i, axis in enumerate(model_info.axis):
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
                self._text_edits["edit:" + suffix] = QtWidgets.QLineEdit(
                    str(model_info.step_sizes[axis])
                )

                layout.addWidget(self._labels["label:" + suffix], offset + i, 0)
                layout.addWidget(self._labels["pos:" + suffix], offset + i, 1)
                layout.addWidget(
                    self._buttons["button:" + suffix + ":up"], offset + i, 2
                )
                layout.addWidget(
                    self._buttons["button:" + suffix + ":down"], offset + i, 3
                )
                layout.addWidget(self._text_edits["edit:" + suffix], offset + i, 4)

                self._buttons["button:" + suffix + ":up"].clicked.connect(
                    lambda _, name=name, axis=axis: self._step(name, axis, True)
                )
                self._buttons["button:" + suffix + ":down"].clicked.connect(
                    lambda _, name=name, axis=axis: self._step(name, axis, False)
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
        step_size = float(self._text_edits["edit:" + motor + ":" + axis].text())
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
