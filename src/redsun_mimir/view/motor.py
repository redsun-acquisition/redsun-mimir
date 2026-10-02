from __future__ import annotations

from typing import TYPE_CHECKING, Any

from psygnal import Signal
from qtpy import QtCore, QtGui, QtWidgets
from redsun import Placement, slot
from redsun.log import Loggable
from redsun.qt import Dock
from redsun.utils.descriptors import parse_map_key

from redsun_mimir.protocols import DescribesMotors  # noqa: TC001

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bluesky.protocols import Descriptor, Reading

_JOG_SPACING = 4

# napari's stylesheet floors QAbstractSpinBox at a 70px min-width plus 10px of
# padding either side, so a narrower request is raised to this
_STEP_WIDTH = 90

# the same floor vertically is an 18px min-height plus 1px of padding
_STEP_HEIGHT = 20

# no min-width: a stylesheet one is written into the widget's minimumWidth when
# the style is polished, overwriting the size the buttons are given in code
_JOG_STYLE = "QPushButton#jog { padding: 0px; }"


def _resized(font: QtGui.QFont, delta: int) -> QtGui.QFont:
    """Return a copy of *font* with its point size shifted by *delta*."""
    resized = QtGui.QFont(font)
    # a font sized in pixels reports -1 here, and setPointSize would then be
    # handed an invalid size
    point_size = resized.pointSize()
    if point_size > 0:
        resized.setPointSize(point_size + delta)
    return resized


class MotorView(QtWidgets.QWidget, Loggable):
    """View for manual motor stage control.

    Builds one control group per motor device from the component describing
    the motors of the session.

    Each axis is one row of its device's group: the axis name, the readback
    position, and a jog strip carrying the step size between the two buttons
    that apply it.

    Parameters
    ----------
    step_size
        Default step size for motor movements, in the engineering unit of the
        motor (e.g. microns).
    """

    placement: Placement = Dock("right")

    sig_motor_move = Signal(str, str, float)
    """Emitted when a step button is pressed, with the motor name, the axis
    and the displacement to apply, signed by the direction of the button."""

    sig_motor_step_stop = Signal(str)
    """Emitted with the motor name when its step button is released."""

    def __init__(
        self,
        name: str,
        parent: QtWidgets.QWidget,
        step_size: float = 100.0,
    ) -> None:
        super().__init__(parent)
        self.name = name
        self.step_size = step_size
        self._labels: dict[str, QtWidgets.QLabel] = {}
        self._buttons: dict[str, QtWidgets.QPushButton] = {}
        self._groups: dict[str, QtWidgets.QGroupBox] = {}
        self._steps: dict[str, QtWidgets.QDoubleSpinBox] = {}
        # each motor's jog strips, disabled while a plan holds the motor
        self._inputs: dict[str, list[QtWidgets.QWidget]] = {}

        self.main_layout = QtWidgets.QVBoxLayout(self)

        self.setStyleSheet(_JOG_STYLE)

        self._readout_font = _resized(
            QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont), 2
        )

    def setup(self, motors: DescribesMotors) -> None:
        """Build the per-axis controls of every motor *motors* describes."""
        self.setup_ui(motors.motor_readings(), motors.motor_descriptors())

    def setup_ui(
        self,
        readings: dict[str, Reading[Any]],
        description: dict[str, Descriptor],
    ) -> None:
        """Create the UI based on the provided readings and description."""
        axis_map: dict[str, list[tuple[str, str]]] = {}
        for key in readings:
            # "units" is optional in the descriptor spec: absent for plain
            # soft signals, so it must not be indexed directly
            units = description[key].get("units") or "NA"
            name, _, axis = parse_map_key(key, "axis")
            axis_map.setdefault(name, []).append((axis, units))

        for name, axes in axis_map.items():
            group = QtWidgets.QGroupBox(name, self)
            group.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
            self._groups[name] = group

            grid = QtWidgets.QGridLayout(group)
            grid.setColumnStretch(1, 1)

            for i, (axis, units) in enumerate(axes):
                suffix = f"{name}:{axis}"
                self._labels["label:" + suffix] = QtWidgets.QLabel(axis, group)
                self._labels["pos:" + suffix] = QtWidgets.QLabel(f"{0:.2f}", group)
                self._labels["pos:" + suffix].setFont(self._readout_font)
                self._labels["pos:" + suffix].setAlignment(
                    QtCore.Qt.AlignmentFlag.AlignRight
                    | QtCore.Qt.AlignmentFlag.AlignVCenter
                )
                self._labels["units:" + suffix] = QtWidgets.QLabel(units, group)

                grid.addWidget(self._labels["label:" + suffix], i, 0)
                grid.addWidget(self._labels["pos:" + suffix], i, 1)
                grid.addWidget(self._labels["units:" + suffix], i, 2)
                grid.addWidget(self._jog_strip(name, axis, units, group), i, 3)

            self.main_layout.addWidget(group)

        self.main_layout.addStretch(1)

    def _jog_strip(
        self, motor: str, axis: str, units: str, parent: QtWidgets.QWidget
    ) -> QtWidgets.QWidget:
        """Build the step control and its two jog buttons as one strip.

        Parameters
        ----------
        motor : str
            Motor device label.
        axis : str
            Motor axis.
        units : str
            Engineering unit of the axis.
        parent : QtWidgets.QWidget
            Widget the strip is built in.
        """
        suffix = f"{motor}:{axis}"
        strip = QtWidgets.QWidget(parent)
        layout = QtWidgets.QHBoxLayout(strip)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(_JOG_SPACING)

        step = QtWidgets.QDoubleSpinBox(strip)
        step.setButtonSymbols(QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons)
        step.setDecimals(2)
        step.setRange(0.0, 1e6)
        step.setValue(self.step_size)
        step.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
        step.setToolTip(f"Step size ({units})")
        # a spin box expands by default, which would leave the buttons beside
        # it a fraction of its width
        step.setFixedSize(_STEP_WIDTH, _STEP_HEIGHT)
        self._steps["step:" + suffix] = step

        side = _STEP_HEIGHT
        for direction, glyph in (("down", "-"), ("up", "+")):
            button = QtWidgets.QPushButton(glyph, strip)
            button.setObjectName("jog")
            button.setFixedSize(side, side)
            button.setFont(_resized(button.font(), 2))
            button.setToolTip(f"Move {axis} by one step, or keep moving while held")
            button.pressed.connect(
                lambda m=motor, a=axis, up=direction == "up": self._step(m, a, up)
            )
            button.released.connect(lambda m=motor: self.sig_motor_step_stop.emit(m))
            self._buttons[f"button:{suffix}:{direction}"] = button

        layout.addWidget(self._buttons[f"button:{suffix}:up"])
        layout.addWidget(step)
        layout.addWidget(self._buttons[f"button:{suffix}:down"])
        self._inputs.setdefault(motor, []).append(strip)
        return strip

    @slot
    def set_locked(self, names: frozenset[str]) -> None:
        """Disable the controls of the motors in *names*, and enable the rest.

        Positions keep updating: only the jog controls are disabled.
        """
        for device, inputs in self._inputs.items():
            for widget in inputs:
                widget.setEnabled(device not in names)

    def _step(self, motor: str, axis: str, direction_up: bool) -> None:
        """Start stepping the motor by the step size.

        Parameters
        ----------
        direction_up
            If `True`, increase the motor's position.
        """
        # a displacement, never a target computed from the position label: the
        # label only refreshes once a move completes, so two quick clicks would
        # both read the pre-move value and ask for the same absolute position
        step_size = self._steps[f"step:{motor}:{axis}"].value()
        self.sig_motor_move.emit(motor, axis, step_size if direction_up else -step_size)

    @slot
    def update_setpoint(self, reading: Mapping[str, Reading[Any]]) -> None:
        """Write an axis reading, keyed `<device>-axis-<name>`, into its label."""
        for key, value in reading.items():
            motor, _, axis = parse_map_key(key, "axis")
            self._labels[f"pos:{motor}:{axis}"].setText(f"{value['value']:.2f}")
