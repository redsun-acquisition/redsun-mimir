from __future__ import annotations

from typing import TYPE_CHECKING, Any

import in_n_out as ino
from qtpy import QtCore, QtGui, QtWidgets
from sunflare.log import Loggable
from sunflare.view.qt import QtView
from sunflare.virtual import Signal
from superqt import QLabeledDoubleSlider, QLabeledSlider

from redsun_mimir.protocols import LightProtocol  # noqa: TC001

if TYPE_CHECKING:
    from sunflare.virtual import VirtualBus

store = ino.Store.get_store("LightModelInfo")


class LightWidget(QtView, Loggable):
    sigToggleLightRequest = Signal(str)
    sigIntensityRequest = Signal(str, object)  # name, intensity

    def __init__(
        self,
        virtual_bus: VirtualBus,
        /,
        **kwargs: Any,
    ) -> None:
        super().__init__(virtual_bus, **kwargs)

        self._lights_info: dict[str, LightProtocol] = {}
        self.setWindowTitle("Light sources")

        self.main_layout = QtWidgets.QVBoxLayout()

        self._labels: dict[str, QtWidgets.QLabel] = {}
        self._buttons: dict[str, QtWidgets.QPushButton] = {}
        self._sliders: dict[str, QLabeledDoubleSlider | QLabeledSlider] = {}
        self._groups: dict[str, QtWidgets.QGroupBox] = {}

        # Regular expression for a valid floating-point number
        float_regex = QtCore.QRegularExpression(r"^[-+]?\d*\.?\d+$")
        self.validator = QtGui.QRegularExpressionValidator(float_regex)

        # Inject the setup_ui method to fill the widget with light sources
        setup_ui = store.inject(self.setup_ui)
        setup_ui()

    def setup_ui(self, lights_info: dict[str, LightProtocol]) -> None:
        self._lights_info = lights_info

        for name, light in self._lights_info.items():
            self._groups[name] = QtWidgets.QGroupBox(f"{name} ({light.wavelength} nm)")
            self._groups[name].setAlignment(
                QtCore.Qt.AlignmentFlag.AlignHCenter
                | QtCore.Qt.AlignmentFlag.AlignRight
            )

            layout = QtWidgets.QGridLayout()

            self._buttons[f"on:{name}"] = QtWidgets.QPushButton("ON")
            self._buttons[f"on:{name}"].setCheckable(True)
            self._buttons[f"on:{name}"].clicked.connect(
                lambda _, name=name: self._on_toggle_button_checked(name)
            )

            if not light.binary:
                slider: QLabeledDoubleSlider | QLabeledSlider
                if all(isinstance(i, int) for i in light.intensity_range):
                    slider = QLabeledSlider()
                elif all(isinstance(i, float) for i in light.intensity_range):
                    slider = QLabeledDoubleSlider()
                else:
                    # should never happen...
                    raise TypeError(
                        "Intensity range must be either all integers or all floats."
                    )
                self._sliders[f"power:{name}"] = slider
                self._sliders[f"power:{name}"].setOrientation(
                    QtCore.Qt.Orientation.Horizontal
                )
                self._sliders[f"power:{name}"].setRange(*light.intensity_range)
                self._sliders[f"power:{name}"].setSingleStep(light.step_size)
                self._sliders[f"power:{name}"].valueChanged.connect(
                    lambda value, name=name: self._on_slider_changed(value, name)
                )
                self._sliders[f"power:{name}"]._label.setAlignment(
                    QtCore.Qt.AlignmentFlag.AlignHCenter
                )
                self._labels[f"egu:{name}"] = QtWidgets.QLabel(light.egu)
                layout.addWidget(self._buttons[f"on:{name}"], 0, 0)
                layout.addWidget(self._sliders[f"power:{name}"], 0, 1, 1, 3)
                layout.addWidget(self._labels[f"egu:{name}"], 0, 4)
            else:
                layout.addWidget(self._buttons[f"on:{name}"], 0, 0, 1, 4)

            self._groups[name].setLayout(layout)
            self.main_layout.addWidget(self._groups[name])

        self.setLayout(self.main_layout)

    def registration_phase(self) -> None:
        """Register the widget."""
        self.virtual_bus.register_signals(self)

    def connection_phase(self) -> None:
        """Connect the widget."""
        ...

    def _on_toggle_button_checked(self, name: str) -> None:
        """Toggle the light source."""
        self.sigToggleLightRequest.emit(name)
        if self._buttons[f"on:{name}"].isChecked():
            self._buttons[f"on:{name}"].setText("OFF")
        else:
            self._buttons[f"on:{name}"].setText("ON")

    def _on_slider_changed(self, value: int | float, name: str) -> None:
        """Change the intensity of the light source."""
        self.logger.debug(f"Change intensity of light source {name} to {value:.2f}")
        self.sigIntensityRequest.emit(name, value)
