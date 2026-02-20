from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar, cast

from qtpy import QtCore, QtGui, QtWidgets
from sunflare.view import ViewPosition
from sunflare.view.qt import QtView
from sunflare.virtual import Signal

from redsun_mimir.utils import find_signals
from redsun_mimir.utils.descriptors import parse_key

if TYPE_CHECKING:
    from bluesky.protocols import Descriptor, Reading
    from sunflare.virtual import VirtualContainer

_T = TypeVar("_T")


def _get_prop(
    readings: dict[str, Reading[Any]],
    prop: str,
    default: _T,
) -> _T:
    """Find a reading value by property name suffix.

    Searches all keys whose last backslash-delimited segment matches
    *prop*. This makes the lookup independent of the ``name``
    portion of the canonical key.

    Parameters
    ----------
    readings :
        Flat reading dict (values from ``read_configuration()``).
    prop :
        Property name to match (e.g. ``"egu"``, ``"axis"``).
    default :
        Returned when no matching key is found.
    """
    for key, reading in readings.items():
        # canonical format: name\property  (backslash separator)
        tail = key.rsplit("-", 1)[-1]
        if tail == prop:
            return cast("_T", reading["value"])
    return default


class MotorView(QtView):
    r"""View for manual motor stage control.

    Builds one control group per motor device using configuration
    provided by [`MotorPresenter`][redsun_mimir.presenter.MotorPresenter].

    Parameters
    ----------
    virtual_bus :
        Virtual bus for the session.

    Attributes
    ----------
    sigMotorMove :
        Emitted when the user requests a stage movement.
        Carries motor name (``str``), axis (``str``), and target position
        (``float``).
    sigConfigChanged :
        Emitted when the user changes a configuration parameter.
        Carries device label (``str``, ``name``) and a mapping of
        canonical ``name\property`` keys to new values
        (``dict[str, Any]``).
    r
    """

    sigMotorMove = Signal(str, str, float)
    sigConfigChanged = Signal(str, dict[str, Any])

    @property
    def view_position(self) -> ViewPosition:
        return ViewPosition.RIGHT

    def __init__(
        self,
        name: str,
        /,
        **kwargs: Any,
    ) -> None:
        super().__init__(name)
        # Flat canonical-keyed dicts for the full config
        self._configuration: dict[str, Reading[Any]] = {}
        self._description: dict[str, Descriptor] = {}
        # Per-device-label grouped readings for fast _update_position lookups
        self._device_readings: dict[str, dict[str, Reading[Any]]] = {}
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
        """Register motor view signals in the virtual container."""
        pass  # signals registered after setup_ui

    def inject_dependencies(self, container: VirtualContainer) -> None:
        r"""Inject motor configuration from the DI container and build the UI.

        Retrieves configuration readings (current values) and descriptors
        (metadata) registered by
        [`MotorPresenter.register_providers`][redsun_mimir.presenter.MotorPresenter.register_providers].
        Both are flat dicts keyed by the canonical ``name-property``
        scheme, merging all motor devices.
        """
        configuration: dict[str, Reading[Any]] = container.motor_configuration()
        description: dict[str, Descriptor] = container.motor_description()
        self.setup_ui(configuration, description)
        container.register_signals(self)
        sigs = find_signals(container, ["sigNewPosition"])
        if "sigNewPosition" in sigs:
            sigs["sigNewPosition"].connect(self._update_position, thread="main")

    def setup_ui(
        self,
        configuration: dict[str, Reading[Any]],
        description: dict[str, Descriptor],
    ) -> None:
        r"""Build the UI from configuration readings and descriptors.

        Parameters
        ----------
        configuration : ``dict[str, Reading[Any]]``
            Flat mapping of canonical ``name\property`` keys to readings,
            merging all motor devices.
        description : ``dict[str, Descriptor]``
            Flat mapping of canonical ``name\property`` keys to
            descriptors, merging all motor devices.
        """
        self._configuration = configuration
        self._description = description

        # Group flat keys by device name
        devices: dict[str, dict[str, Reading[Any]]] = {}
        for key, reading in configuration.items():
            try:
                name, _ = parse_key(key)
            except ValueError:
                continue
            devices.setdefault(name, {})[key] = reading

        self._device_readings = devices

        for device_label, readings in devices.items():
            egu: str = _get_prop(readings, "egu", "")
            axis: list[str] = _get_prop(readings, "axis", [])

            self._groups[device_label] = QtWidgets.QGroupBox(device_label)
            self._groups[device_label].setAlignment(
                QtCore.Qt.AlignmentFlag.AlignHCenter
            )

            layout = QtWidgets.QGridLayout()

            for i, ax in enumerate(axis):
                suffix = f"{device_label}:{ax}"
                initial_step: float = _get_prop(readings, f"{ax}_step_size", 1.0)

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
                    lambda _, lbl=device_label, a=ax: self._step(lbl, a, True)
                )
                self._buttons["button:" + suffix + ":down"].clicked.connect(
                    lambda _, lbl=device_label, a=ax: self._step(lbl, a, False)
                )
                self._line_edits["edit:" + suffix].editingFinished.connect(
                    lambda lbl=device_label, a=ax: self._validate_and_notify(lbl, a)
                )

            self._groups[device_label].setLayout(layout)
            self.main_layout.addWidget(self._groups[device_label])

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

    def _update_position(self, motor: str, axis: str, position: float) -> None:
        """Update the motor position label.

        Parameters
        ----------
        motor : ``str``
            Motor device label (``name``).
        axis : ``str``
            Motor axis.
        position : ``float``
            New position of the motor.
        """
        dev_readings = self._device_readings.get(motor, {})
        egu: str = _get_prop(dev_readings, "egu", "")
        self._labels[f"pos:{motor}:{axis}"].setText(f"{position:.2f} {egu}")

    def _validate_and_notify(self, device_label: str, axis: str) -> None:
        r"""Validate the new step size value and notify the virtual bus.

        Emits ``sigConfigChanged`` with the device label and a mapping of
        canonical ``name\property`` keys to new values, so the
        presenter can route them directly to the device's ``set()`` call.

        Parameters
        ----------
        device_label : ``str``
            Motor device label (``name``).
        axis : ``str``
            Motor axis.
        """
        text = self._line_edits["edit:" + device_label + ":" + axis].text()
        state = self.validator.validate(text, 0)[0]
        if state == QtGui.QRegularExpressionValidator.State.Invalid:
            self._line_edits["edit:" + device_label + ":" + axis].setStyleSheet(
                "border: 2px solid red;"
            )
        else:
            self._line_edits["edit:" + device_label + ":" + axis].setStyleSheet("")

        if state == QtGui.QRegularExpressionValidator.State.Acceptable:
            # Resolve canonical keys from the flat config dict
            axis_key = next(
                (
                    k
                    for k in self._configuration
                    if k.startswith(device_label) and k.rsplit("-", 1)[-1] == "axis"
                ),
                f"{device_label}-axis",
            )
            step_key = next(
                (
                    k
                    for k in self._configuration
                    if k.startswith(device_label)
                    and k.rsplit("-", 1)[-1] == f"{axis}_step_size"
                ),
                f"{device_label}-{axis}_step_size",
            )
            self.sigConfigChanged.emit(
                device_label,
                {axis_key: axis, step_key: float(text)},
            )
