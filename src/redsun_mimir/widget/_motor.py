from __future__ import annotations

from typing import TYPE_CHECKING, Any

import in_n_out as ino
from qtpy import QtCore, QtGui, QtWidgets
from sunflare.view.qt import BaseQtWidget
from sunflare.virtual import Signal

from redsun_mimir.model import MotorModelInfo  # noqa: TC001

if TYPE_CHECKING:
    from bluesky.protocols import Descriptor, Reading
    from sunflare.config import ViewInfoProtocol
    from sunflare.virtual import VirtualBus


class MotorWidget(BaseQtWidget):
    """Motor widget for Redsun Mimir.

    Parameters
    ----------
    config : ``ViewInfoProtocol``
        View configuration information.
    virtual_bus : ``VirtualBus``
        Virtual bus for the session.

    Attributes
    ----------
    sigMotorMove : ``Signal[str, str, float]``
        Signal emitted when a stage is moved.
        - ``str``: motor name
        - ``str``: motor axis
        - ``float``: stage new position
    sigConfigChanged : ``Signal[str, dict[str, Any]]``
        Signal emitted when a configuration value is changed.
        - ``str``: motor name
        - ``dict[str, Any]``: mapping of configuration parameters to new values

    """

    sigMotorMove = Signal(str, str, float)
    sigConfigChanged = Signal(str, dict[str, Any])

    def __init__(
        self,
        config: ViewInfoProtocol,
        virtual_bus: VirtualBus,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(config, virtual_bus, *args, **kwargs)
        self._description: dict[str, dict[str, Descriptor]] = {}
        self._configuration: dict[str, dict[str, Reading[Any]]] = {}
        self._labels: dict[str, QtWidgets.QLabel] = {}
        self._buttons: dict[str, QtWidgets.QPushButton] = {}
        self._groups: dict[str, QtWidgets.QGroupBox] = {}
        self._line_edits: dict[str, QtWidgets.QLineEdit] = {}

        self.main_layout = QtWidgets.QVBoxLayout()

        # Regular expression for a valid floating-point number
        float_regex = QtCore.QRegularExpression(r"^[-+]?\d*\.?\d+$")
        self.validator = QtGui.QRegularExpressionValidator(float_regex)

        vline = QtWidgets.QFrame()
        vline.setFrameShape(QtWidgets.QFrame.Shape.VLine)
        vline.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)

        self.store = ino.Store.get_store("MotorModelInfo")
        self.store.inject(self.setup_ui)()

    def setup_ui(self, motors_info: dict[str, MotorModelInfo]) -> None:
        self._motors_info = motors_info

        # setup the layout and connect the signals
        for name, model_info in self._motors_info.items():
            self._groups[name] = QtWidgets.QGroupBox(name)
            self._groups[name].setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)

            # group layout
            layout = QtWidgets.QGridLayout()

            for i, axis in enumerate(model_info.axis):
                # create the views
                suffix = f"{name}:{axis}"
                self._labels["label:" + suffix] = QtWidgets.QLabel(f"{axis}")
                self._labels["label:" + suffix].setTextFormat(
                    QtCore.Qt.TextFormat.RichText
                )
                self._labels["pos:" + suffix] = QtWidgets.QLabel(
                    f"{0:.2f} {model_info.egu}"
                )
                self._buttons["button:" + suffix + ":up"] = QtWidgets.QPushButton("+")
                self._buttons["button:" + suffix + ":down"] = QtWidgets.QPushButton("-")
                self._labels["step:" + suffix] = QtWidgets.QLabel("Step size: ")
                self._line_edits["edit:" + suffix] = QtWidgets.QLineEdit(
                    str(model_info.step_sizes[axis])
                )
                self._line_edits["edit:" + suffix].setAlignment(
                    QtCore.Qt.AlignmentFlag.AlignHCenter
                )

                # setup the layout
                layout.addWidget(self._labels["label:" + suffix], i, 0)
                layout.addWidget(self._labels["pos:" + suffix], i, 1)
                layout.addWidget(self._buttons["button:" + suffix + ":up"], i, 2)
                layout.addWidget(self._buttons["button:" + suffix + ":down"], i, 3)
                layout.addWidget(self._labels["step:" + suffix], i, 5)
                layout.addWidget(self._line_edits["edit:" + suffix], i, 6)

                # connect the signals
                self._buttons["button:" + suffix + ":up"].clicked.connect(
                    lambda _, name=name, axis=axis: self._step(name, axis, True)
                )
                self._buttons["button:" + suffix + ":down"].clicked.connect(
                    lambda _, name=name, axis=axis: self._step(name, axis, False)
                )

                self._line_edits["edit:" + suffix].editingFinished.connect(
                    lambda name=name, axis=axis: self._validate_and_notify(name, axis)
                )
            self._groups[name].setLayout(layout)
            self.main_layout.addWidget(self._groups[name])

        self.setLayout(self.main_layout)

    def registration_phase(self) -> None:
        """Register your signals to the virtual bus."""
        self.virtual_bus.register_signals(self)

    def connection_phase(self) -> None:
        """Connect your signals to the virtual bus.

        The controller layer will be already built when this method is called.
        We use it to directly build the GUI by retrieving a configuration of
        the currently allocated motors to create the proper widget layout.
        """
        self.virtual_bus["MotorController"]["sigNewPosition"].connect(
            self._update_position, thread="main"
        )

    def _step(self, motor: str, axis: str, direction_up: bool) -> None:
        """Move the motor by a step size.

        Parameters
        ----------
        motor : ``str``
            Motor name.
        axis : ``str``
            Motor axis.
        direction_up : ``bool``
            If `True`, increase motor's position.
        """
        current_position = float(
            self._labels["pos:" + motor + ":" + axis].text().split()[0]
        )
        step_size = float(self._line_edits["edit:" + motor + ":" + axis].text())
        if direction_up:
            self.sigMotorMove.emit(motor, axis, current_position + step_size)
        else:
            self.sigMotorMove.emit(motor, axis, current_position - step_size)

    def _update_position(self, motor: str, axis: str, position: float) -> None:
        """Update the motor position.

        Parameters
        ----------
        motor : ``str``
            Motor name.
        axis : ``str``
            Motor axis.
        position : ``float``
            New position of the motor.
        """
        new_pos = f"{position:.2f} {self._motors_info[motor].egu}"
        self._labels[f"pos:{motor}:{axis}"].setText(new_pos)

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
            self.sigConfigChanged.emit(name, {"axis": axis, "step_size": float(text)})
