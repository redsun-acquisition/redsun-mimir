from __future__ import annotations

from typing import TYPE_CHECKING, Any

from qtpy import QtCore, QtGui, QtWidgets
from redsun.log import Loggable
from redsun.utils.descriptors import parse_key
from redsun.view import ViewPosition
from redsun.view.qt import QtView
from redsun.virtual import Signal
from superqt import QLabeledDoubleSlider, QLabeledSlider

if TYPE_CHECKING:
    from bluesky.protocols import Descriptor, Reading
    from redsun.virtual import VirtualContainer

# Key format templates for widget dictionaries
_KEY_GROUP = "{label}"
_KEY_BUTTON_ON = "on:{label}"
_KEY_SLIDER_POWER = "power:{label}"
_KEY_LABEL_EGU = "egu:{label}"


def _group_key(label: str) -> str:
    return _KEY_GROUP.format(label=label)


def _button_on_key(label: str) -> str:
    return _KEY_BUTTON_ON.format(label=label)


def _slider_power_key(label: str) -> str:
    return _KEY_SLIDER_POWER.format(label=label)


def _label_egu_key(label: str) -> str:
    return _KEY_LABEL_EGU.format(label=label)


class LightView(QtView, Loggable):
    """View for light source toggle and intensity control.

    Builds one control group per light device using configuration
    provided by [`LightPresenter`][redsun_mimir.presenter.LightPresenter].

    Parameters
    ----------
    name: str
        Identity key of the view.

    Attributes
    ----------
    sigToggleLightRequest : Signal[str]
        Emitted when the user toggles a light source on or off.
        Carries the light source device label (``str``, ``prefix:name``).
    sigIntensityRequest : Signal[str, Any]
        Emitted when the user adjusts a light source intensity.
        Carries the light source device label (``str``) and the new
        intensity value.
    """

    sigToggleLightRequest = Signal(str)
    sigIntensityRequest = Signal(str, object)  # device_label, intensity

    @property
    def view_position(self) -> ViewPosition:
        """The position in the main view."""
        return ViewPosition.RIGHT

    def __init__(
        self,
        name: str,
        /,
    ) -> None:
        super().__init__(name)

        self._configuration: dict[str, Reading[Any]] = {}
        self._description: dict[str, Descriptor] = {}
        self.setWindowTitle("Light sources")

        self.main_layout = QtWidgets.QVBoxLayout()

        self._labels: dict[str, QtWidgets.QLabel] = {}
        self._buttons: dict[str, QtWidgets.QPushButton] = {}
        self._sliders: dict[str, QLabeledDoubleSlider | QLabeledSlider] = {}
        self._groups: dict[str, QtWidgets.QGroupBox] = {}

        float_regex = QtCore.QRegularExpression(r"^[-+]?\d*\.?\d+$")
        self.validator = QtGui.QRegularExpressionValidator(float_regex)

    def register_providers(self, container: VirtualContainer) -> None:
        """Build the UI and register light view signals in the virtual container."""
        container.register_signals(self)

    def inject_dependencies(self, container: VirtualContainer) -> None:
        """Connect inbound signals from the light presenter and build the UI."""
        configuration: dict[str, Reading[Any]] = container.light_configuration()
        description: dict[str, Descriptor] = container.light_description()
        self.setup_ui(configuration, description)

    def setup_ui(
        self,
        readings: dict[str, Reading[Any]],
        description: dict[str, Descriptor],
    ) -> None:
        """Create the UI from configuration readings and descriptors."""
        # map of device name to list of reading names and units
        reading_names: dict[str, list[str]] = {}
        reading_units: dict[str, str] = {}
        for key in readings.keys():
            try:
                units = description[key]["units"] or "NA"
            except KeyError:
                units = "NA"
            name, prop = parse_key(key)
            reading_names.setdefault(name, []).append(prop)
            reading_units.setdefault(name, units)

        for name, props in reading_names.items():
            layout = QtWidgets.QGridLayout()
            if "wavelength" in props:
                wavelength = readings[f"{name}-wavelength"]["value"]
            units = reading_units[name]
            self._groups[_group_key(name)] = QtWidgets.QGroupBox(
                f"{name} ({wavelength} nm)"
            )
            self._groups[_group_key(name)].setAlignment(
                QtCore.Qt.AlignmentFlag.AlignHCenter
                | QtCore.Qt.AlignmentFlag.AlignRight
            )
            self._groups[_group_key(name)].setLayout(layout)
            self._buttons[_button_on_key(name)] = QtWidgets.QPushButton("ON")
            self._buttons[_button_on_key(name)].setCheckable(True)
            self._buttons[_button_on_key(name)].clicked.connect(
                lambda _, lbl=name: self._on_toggle_button_checked(lbl)
            )
            slider: QLabeledDoubleSlider | QLabeledSlider
            range: list[int | float]
            dtype = description[f"{name}-intensity"]["dtype"]
            if dtype == "number":
                slider = QLabeledDoubleSlider(QtCore.Qt.Orientation.Horizontal)
                range = [0.0, 100.0]  # TODO: get from descriptor
            elif dtype == "integer":
                slider = QLabeledSlider(QtCore.Qt.Orientation.Horizontal)
                range = [0, 100]  # TODO: get from descriptor
            else:
                raise TypeError(
                    "Intensity descriptor must have dtype 'number' or 'integer'."
                )
            self._sliders[_slider_power_key(name)] = slider
            self._sliders[_slider_power_key(name)].setRange(*range)
            self._sliders[_slider_power_key(name)].valueChanged.connect(
                lambda value, lbl=name: self._on_slider_changed(value, lbl)
            )
            self._labels[_label_egu_key(name)] = QtWidgets.QLabel(units)
            layout.addWidget(self._buttons[_button_on_key(name)], 0, 0)
            layout.addWidget(self._sliders[_slider_power_key(name)], 0, 1, 1, 3)
            layout.addWidget(self._labels[_label_egu_key(name)], 0, 4)

            self._groups[_group_key(name)].setLayout(layout)
            self.main_layout.addWidget(self._groups[_group_key(name)])

        self.setLayout(self.main_layout)

    def _on_toggle_button_checked(self, device_label: str) -> None:
        """Toggle the light source."""
        self.sigToggleLightRequest.emit(device_label)
        if self._buttons[_button_on_key(device_label)].isChecked():
            self._buttons[_button_on_key(device_label)].setText("OFF")
        else:
            self._buttons[_button_on_key(device_label)].setText("ON")

    def _on_slider_changed(self, value: int | float, device_label: str) -> None:
        """Change the intensity of the light source."""
        self.logger.debug(
            f"Change intensity of light source {device_label} to {value:.2f}"
        )
        self.sigIntensityRequest.emit(device_label, value)
