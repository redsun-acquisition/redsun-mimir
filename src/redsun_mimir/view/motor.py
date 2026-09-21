from __future__ import annotations

from typing import TYPE_CHECKING, Any

from qtpy import QtCore, QtGui, QtWidgets
from redsun.log import Loggable
from redsun.utils.descriptors import parse_map_key
from redsun.view import ViewPosition
from redsun.view.qt import QtView
from redsun.virtual import Signal, slot

from redsun_mimir.providers import MOTOR_DESCRIPTION, MOTOR_READBACKS, MOTOR_READINGS

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bluesky.protocols import Descriptor, Reading
    from redsun.virtual import VirtualContainer


class MotorView(QtView, Loggable):
    """View for manual motor stage control.

    One control group per motor, from the configuration
    [`MotorPresenter`][redsun_mimir.presenter.MotorPresenter] provides.

    Parameters
    ----------
    step_size :
        Default step, in the motor's engineering unit (microns, say).

    Attributes
    ----------
    sig_motor_move :
        Emitted when the user asks for a move, with the motor name, the axis
        and the displacement, signed by the direction of the button.
    """

    sig_motor_move = Signal(str, str, float)

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

        self.main_layout = QtWidgets.QVBoxLayout(self)

        float_regex = QtCore.QRegularExpression(r"^[-+]?\d*\.?\d+$")
        self.validator = QtGui.QRegularExpressionValidator(float_regex)

    def register_providers(self, container: VirtualContainer) -> None:
        """Register the view's signals with the container."""
        container.register_signals(self)

    def inject_dependencies(self, container: VirtualContainer) -> None:
        """Build the per-axis controls, then subscribe to each axis readback.

        Subscribing delivers the current reading at once, so the labels it
        writes to must exist first.
        """
        self.setup_ui(
            container.require(MOTOR_READINGS), container.require(MOTOR_DESCRIPTION)
        )
        for readback in container.require(MOTOR_READBACKS).values():
            container.subscribe(readback, self.update_setpoint)

    def setup_ui(
        self,
        readings: dict[str, Reading[Any]],
        description: dict[str, Descriptor],
    ) -> None:
        """Build one control group per motor, with a row per axis."""
        axis_map: dict[str, list[str]] = {}
        axis_units: dict[str, list[str]] = {}
        for key in readings:
            # "units" is optional in the descriptor spec: absent for plain
            # soft signals, so it must not be indexed directly
            units = description[key].get("units") or "NA"
            name, _, axis = parse_map_key(key, "axis")
            axis_map.setdefault(name, []).append(axis)
            axis_units.setdefault(name, []).append(units)

        for name, axes in axis_map.items():
            self._groups.setdefault(name, QtWidgets.QGroupBox(name, self))
            self._groups[name].setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
            layout = QtWidgets.QGridLayout(self._groups[name])

            for i, axis in enumerate(axes):
                suffix = f"{name}:{axis}"
                units = axis_units[name][i]
                self._labels["label:" + suffix] = QtWidgets.QLabel(
                    f"{axis}", self._groups[name]
                )
                self._labels["label:" + suffix].setTextFormat(
                    QtCore.Qt.TextFormat.RichText
                )
                self._labels["pos:" + suffix] = QtWidgets.QLabel(
                    f"{0:.2f} {units}", self._groups[name]
                )
                self._buttons["button:" + suffix + ":up"] = QtWidgets.QPushButton(
                    "+", self._groups[name]
                )
                self._buttons["button:" + suffix + ":down"] = QtWidgets.QPushButton(
                    "-", self._groups[name]
                )
                self._labels["step:" + suffix] = QtWidgets.QLabel(
                    f"step ({units})", self._groups[name]
                )
                self._line_edits["edit:" + suffix] = QtWidgets.QLineEdit(
                    str(self.step_size), self._groups[name]
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

            self.main_layout.addWidget(self._groups[name])

    def _step(self, motor: str, axis: str, direction_up: bool) -> None:
        """Ask for a move of *axis* by the step in its edit, up or down."""
        # a displacement, never a target computed from the position label: the
        # label only refreshes once a move completes, so two quick clicks would
        # both read the pre-move value and ask for the same absolute position
        step_size = float(self._line_edits["edit:" + motor + ":" + axis].text())
        self.sig_motor_move.emit(motor, axis, step_size if direction_up else -step_size)

    @slot
    def update_setpoint(self, reading: Mapping[str, Reading[Any]]) -> None:
        """Write an axis reading into its position label.

        *reading* holds one axis, keyed ``<device>-axis-<name>``.
        """
        for key, value in reading.items():
            motor, _, axis = parse_map_key(key, "axis")
            _, units = self._labels[f"step:{motor}:{axis}"].text().split()
            self._labels[f"pos:{motor}:{axis}"].setText(f"{value['value']:.2f} {units}")

    def _validate(self, motor: str, axis: str) -> None:
        """Outline the step edit of *axis* in red when its text is not a number."""
        text = self._line_edits[f"edit:{motor}:{axis}"].text()
        state = self.validator.validate(text, 0)[0]
        if state == QtGui.QRegularExpressionValidator.State.Invalid:
            self._line_edits[f"edit:{motor}:{axis}"].setStyleSheet(
                "border: 2px solid red;"
            )
        else:
            self._line_edits[f"edit:{motor}:{axis}"].setStyleSheet("")
