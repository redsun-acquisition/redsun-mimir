from __future__ import annotations

from typing import TYPE_CHECKING, Any

from qtpy import QtCore, QtGui, QtWidgets
from redsun.utils import find_signals
from redsun.utils.descriptors import parse_map_key
from redsun.view import ViewPosition
from redsun.view.qt import QtView
from redsun.virtual import Signal

if TYPE_CHECKING:
    from bluesky.protocols import Descriptor, Reading
    from redsun.virtual import VirtualContainer


class MotorView(QtView):
    """View for manual motor stage control.

    Builds one control group per motor device using configuration
    provided by [`MotorPresenter`][redsun_mimir.presenter.MotorPresenter].

    Parameters
    ----------
    name : str
        Identity key of the view.
    step_size : float, optional
        Default step size for motor movements,
        in the engineering unit of the motor
        (e.g. microns).

        Defaults to ``100.0``.

    Attributes
    ----------
    sigMotorMove :
        Emitted when the user requests a stage movement.
        Carries motor name (``str``), axis (``str``), and target position
        (``float``).
    """

    sigMotorMove = Signal(str, str, float)

    @property
    def view_position(self) -> ViewPosition:
        """The position in the main view."""
        return ViewPosition.RIGHT

    def __init__(
        self,
        name: str,
        /,
        step_size: float = 10.0,
    ) -> None:
        super().__init__(name)
        self.step_size = step_size
        self._labels: dict[str, QtWidgets.QLabel] = {}
        self._buttons: dict[str, QtWidgets.QPushButton] = {}
        self._groups: dict[str, QtWidgets.QGroupBox] = {}
        self._line_edits: dict[str, QtWidgets.QLineEdit] = {}

        self.main_layout = QtWidgets.QVBoxLayout()

        float_regex = QtCore.QRegularExpression(r"^[-+]?\d*\.?\d+$")
        self.validator = QtGui.QRegularExpressionValidator(float_regex)

        vline = QtWidgets.QFrame()
        vline.setFrameShape(QtWidgets.QFrame.Shape.VLine)
        vline.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)

    def register_providers(self, container: VirtualContainer) -> None:
        """Build the UI and register motor view signals in the virtual container."""
        container.register_signals(self)

    def inject_dependencies(self, container: VirtualContainer) -> None:
        """Connect inbound signals from the motor presenter."""
        readings: dict[str, Reading[Any]] = container.motor_readings()
        description: dict[str, Descriptor] = container.motor_description()
        self.setup_ui(readings, description)

        sigs = find_signals(container, ["sigNewPosition", "sigNewConfiguration"])
        if "sigNewPosition" in sigs:
            sigs["sigNewPosition"].connect(self._update_setpoint, thread="main")

    def setup_ui(
        self,
        readings: dict[str, Reading[Any]],
        description: dict[str, Descriptor],
    ) -> None:
        """Create the UI based on the provided readings and description."""
        axis_map: dict[str, list[str]] = {}
        axis_units: dict[str, list[str]] = {}
        for key in readings.keys():
            units = description[key]["units"] or "NA"
            name, _, axis = parse_map_key(key, "axis")
            axis_map.setdefault(name, list()).append(axis)
            axis_units.setdefault(name, list()).append(units)

        for name, axes in axis_map.items():
            layout = QtWidgets.QGridLayout()
            self._groups.setdefault(name, QtWidgets.QGroupBox(name))
            self._groups[name].setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)

            for i, axis in enumerate(axes):
                suffix = f"{name}:{axis}"
                units = axis_units[name][i]
                self._labels["label:" + suffix] = QtWidgets.QLabel(f"{axis}")
                self._labels["label:" + suffix].setTextFormat(
                    QtCore.Qt.TextFormat.RichText
                )
                self._labels["pos:" + suffix] = QtWidgets.QLabel(f"{0:.2f} {units}")
                self._buttons["button:" + suffix + ":up"] = QtWidgets.QPushButton("+")
                self._buttons["button:" + suffix + ":down"] = QtWidgets.QPushButton("-")
                self._labels["step:" + suffix] = QtWidgets.QLabel(f"step ({units})")
                self._line_edits["edit:" + suffix] = QtWidgets.QLineEdit(
                    str(self.step_size)
                )
                self._line_edits["edit:" + suffix].setAlignment(
                    QtCore.Qt.AlignmentFlag.AlignHCenter
                )

                layout.addWidget(self._labels["label:" + suffix], i, 0)
                layout.addWidget(self._labels["pos:" + suffix], i, 1)
                layout.addWidget(self._buttons["button:" + suffix + ":up"], i, 2)
                layout.addWidget(self._buttons["button:" + suffix + ":down"], i, 3)
                layout.addWidget(self._labels["step:" + suffix], i, 5)
                layout.addWidget(self._line_edits["edit:" + suffix], i, 6)

                self._buttons["button:" + suffix + ":up"].clicked.connect(
                    lambda _, lbl=name, a=axis: self._step(lbl, a, True)
                )
                self._buttons["button:" + suffix + ":down"].clicked.connect(
                    lambda _, lbl=name, a=axis: self._step(lbl, a, False)
                )
                self._line_edits["edit:" + suffix].editingFinished.connect(
                    lambda lbl=name, a=axis: self._validate(lbl, a)
                )

            self._groups[name].setLayout(layout)
            self.main_layout.addWidget(self._groups[name])

        self.setLayout(self.main_layout)

    def _step(self, motor: str, axis: str, direction_up: bool) -> None:
        """Move the motor by a step size.

        Parameters
        ----------
        motor : ``str``
            Motor device label (``name``).
        axis : ``str``
            Motor axis.
        direction_up : ``bool``
            If ``True``, increase motor's position.
        """
        current_position = float(
            self._labels["pos:" + motor + ":" + axis].text().split()[0]
        )
        step_size = float(self._line_edits["edit:" + motor + ":" + axis].text())
        if direction_up:
            self.sigMotorMove.emit(motor, axis, current_position + step_size)
        else:
            self.sigMotorMove.emit(motor, axis, current_position - step_size)

    def _update_setpoint(self, motor: str, axis: str, position: float) -> None:
        """Update the current motor setpoint as text.

        Parameters
        ----------
        motor : str
            Motor device label.
        axis : str
            Motor axis.
        position : float
            New position of the motor.
        """
        _, units = self._labels[f"step:{motor}:{axis}"].text().split()
        self._labels[f"pos:{motor}:{axis}"].setText(f"{position:.2f} {units}")

    def _validate(self, motor: str, axis: str) -> None:
        """Validate the new step size.

        Parameters
        ----------
        motor : str
            Motor device label.
        axis : str
            Motor axis.
        """
        text = self._line_edits[f"edit:{motor}:{axis}"].text()
        state = self.validator.validate(text, 0)[0]
        if state == QtGui.QRegularExpressionValidator.State.Invalid:
            self._line_edits[f"edit:{motor}:{axis}"].setStyleSheet(
                "border: 2px solid red;"
            )
        else:
            self._line_edits[f"edit:{motor}:{axis}"].setStyleSheet("")
