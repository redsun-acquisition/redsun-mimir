from typing import Any

from qtpy import QtCore, QtGui, QtWidgets
from sunflare.config import RedSunSessionInfo
from sunflare.log import Loggable
from sunflare.view.qt import BaseQtWidget
from sunflare.virtual import Signal, VirtualBus
from superqt import QLabeledDoubleSlider

from redsun_mimir.model import LightModelInfo


class LightWidget(BaseQtWidget, Loggable):
    sigToggleLightRequest = Signal(str)
    sigIntensityRequest = Signal(str, float)

    def __init__(
        self,
        config: RedSunSessionInfo,
        virtual_bus: VirtualBus,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(config, virtual_bus, *args, **kwargs)

        self._lights_info: dict[str, LightModelInfo] = {
            name: value
            for name, value in config.models.items()
            if isinstance(value, LightModelInfo)
        }
        self.setWindowTitle("Light sources")

        main_layout = QtWidgets.QVBoxLayout()

        self._labels: dict[str, QtWidgets.QLabel] = {}
        self._buttons: dict[str, QtWidgets.QPushButton] = {}
        self._sliders: dict[str, QLabeledDoubleSlider] = {}
        self._groups: dict[str, QtWidgets.QGroupBox] = {}

        # Regular expression for a valid floating-point number
        float_regex = QtCore.QRegularExpression(r"^[-+]?\d*\.?\d+$")
        self.validator = QtGui.QRegularExpressionValidator(float_regex)

        for name, model_info in self._lights_info.items():
            self._groups[name] = QtWidgets.QGroupBox(
                f"{name} ({model_info.wavelength} nm)"
            )
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

            if not model_info.binary:
                self._sliders[f"power:{name}"] = QLabeledDoubleSlider()
                self._sliders[f"power:{name}"].setOrientation(
                    QtCore.Qt.Orientation.Horizontal
                )
                self._sliders[f"power:{name}"].setRange(*model_info.intensity_range)  # type: ignore
                self._sliders[f"power:{name}"].setSingleStep(model_info.step_size)
                self._sliders[f"power:{name}"].valueChanged.connect(
                    lambda value, name=name: self._on_slider_changed(value, name)
                )
                self._sliders[f"power:{name}"]._label.setAlignment(
                    QtCore.Qt.AlignmentFlag.AlignHCenter
                )
                self._labels[f"egu:{name}"] = QtWidgets.QLabel(model_info.egu)

            if model_info.binary:
                layout.addWidget(self._buttons[f"on:{name}"], 0, 0, 1, 4)
            else:
                layout.addWidget(self._buttons[f"on:{name}"], 0, 0)
                layout.addWidget(self._sliders[f"power:{name}"], 0, 1, 1, 3)
                layout.addWidget(self._labels[f"egu:{name}"], 0, 4)

            self._groups[name].setLayout(layout)
            main_layout.addWidget(self._groups[name])

        self.setLayout(main_layout)

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

    def _on_slider_changed(self, value: float, name: str) -> None:
        """Change the intensity of the light source."""
        self.debug(f"Change intensity of light source {name} to {value:.2f}")
        self.sigIntensityRequest.emit(name, value)
