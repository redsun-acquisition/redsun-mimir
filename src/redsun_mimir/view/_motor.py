from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar, cast

from qtpy import QtCore, QtGui, QtWidgets
from redsun.config import ViewPositionTypes
from sunflare.view.qt import QtView
from sunflare.virtual import Signal

if TYPE_CHECKING:
    from bluesky.protocols import Descriptor, Reading
    from dependency_injector.containers import DynamicContainer
    from sunflare.virtual import VirtualBus

_T = TypeVar("_T")


def _get_value(
    readings: dict[str, Reading[Any]],
    key: str,
    default: _T,
) -> _T:
    """Safely extract the ``value`` field from a :class:`bluesky.protocols.Reading` entry.

    Parameters
    ----------
    readings : ``dict[str, Reading[Any]]``
        A mapping of key → Reading produced by ``read_configuration()``.
    key : ``str``
        The key to look up.
    default : ``_T``
        The value returned when *key* is absent.

    Returns
    -------
    ``_T``
        The ``value`` field of the Reading, or *default*.
    """
    entry = readings.get(key)
    if entry is None:
        return default
    return cast("_T", entry["value"])


class MotorWidget(QtView):
    """Motor widget for Redsun Mimir.

    Parameters
    ----------
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

    position = ViewPositionTypes.CENTER

    def __init__(
        self,
        virtual_bus: VirtualBus,
        /,
        **kwargs: Any,
    ) -> None:
        super().__init__(virtual_bus, **kwargs)
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

    def inject_dependencies(self, container: DynamicContainer) -> None:
        """Inject motor configuration from the DI container and build the UI.

        Retrieves configuration readings (current values) and descriptors
        (metadata) registered by ``MotorController.register_providers``.
        """
        configuration: dict[str, dict[str, Reading[Any]]] = (
            container.motor_configuration()
        )
        description: dict[str, dict[str, Descriptor]] = container.motor_description()
        self.setup_ui(configuration, description)

    def setup_ui(
        self,
        configuration: dict[str, dict[str, Reading[Any]]],
        description: dict[str, dict[str, Descriptor]],
    ) -> None:
        """Build the UI from configuration readings and descriptors.

        Parameters
        ----------
        configuration : ``dict[str, dict[str, Reading[Any]]]``
            Mapping of motor names to their current configuration readings.
            Each inner dict maps ``"<motor>:<key>"`` strings to Reading dicts.
        description : ``dict[str, dict[str, Descriptor]]``
            Mapping of motor names to their configuration descriptors.
            Each inner dict maps ``"<motor>:<key>"`` strings to Descriptor dicts.
        """
        self._description = description
        self._configuration = configuration

        for name, readings in configuration.items():
            egu: str = _get_value(readings, f"{name}:egu", "")
            axis: list[str] = _get_value(readings, f"{name}:axis", [])

            self._groups[name] = QtWidgets.QGroupBox(name)
            self._groups[name].setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)

            layout = QtWidgets.QGridLayout()

            for i, ax in enumerate(axis):
                suffix = f"{name}:{ax}"
                initial_step: float = _get_value(
                    readings, f"{name}:step_size:{ax}", 1.0
                )

                self._labels["label:" + suffix] = QtWidgets.QLabel(f"{ax}")
                self._labels["label:" + suffix].setTextFormat(
                    QtCore.Qt.TextFormat.RichText
                )
                self._labels["pos:" + suffix] = QtWidgets.QLabel(f"{0:.2f} {egu}")
                self._buttons["button:" + suffix + ":up"] = QtWidgets.QPushButton("+")
                self._buttons["button:" + suffix + ":down"] = QtWidgets.QPushButton("-")
                self._labels["step:" + suffix] = QtWidgets.QLabel("Step size: ")
                self._line_edits["edit:" + suffix] = QtWidgets.QLineEdit(
                    str(initial_step)
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
                    lambda _, name=name, axis=ax: self._step(name, axis, True)
                )
                self._buttons["button:" + suffix + ":down"].clicked.connect(
                    lambda _, name=name, axis=ax: self._step(name, axis, False)
                )
                self._line_edits["edit:" + suffix].editingFinished.connect(
                    lambda name=name, axis=ax: self._validate_and_notify(name, axis)
                )

            self._groups[name].setLayout(layout)
            self.main_layout.addWidget(self._groups[name])

        self.setLayout(self.main_layout)

        self.virtual_bus.register_signals(self)

    def connect_to_virtual(self) -> None:
        """Register signals and connect to virtual bus."""
        self.virtual_bus.signals["MotorController"]["sigNewPosition"].connect(
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
        """Update the motor position label.

        Parameters
        ----------
        motor : ``str``
            Motor name.
        axis : ``str``
            Motor axis.
        position : ``float``
            New position of the motor.
        """
        motor_readings = self._configuration.get(motor, {})
        egu: str = _get_value(motor_readings, f"{motor}:egu", "")
        new_pos = f"{position:.2f} {egu}"
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
