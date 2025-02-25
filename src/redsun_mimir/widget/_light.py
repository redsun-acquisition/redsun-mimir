from typing import Any

from qtpy import QtCore, QtWidgets
from sunflare.config import RedSunSessionInfo
from sunflare.view.qt import BaseQtWidget
from sunflare.virtual import Signal, VirtualBus

from redsun_mimir.model import LightModelInfo


class LightWidget(BaseQtWidget):
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

        # main_layout = QtWidgets.QHBoxLayout()

        self._labels: dict[str, QtWidgets.QLabel] = {}
        self._buttons: dict[str, QtWidgets.QPushButton] = {}
        self._groups: dict[str, QtWidgets.QGroupBox] = {}

        for name, model_info in self._lights_info.items():
            self._groups[name] = QtWidgets.QGroupBox(
                f"{name} ({model_info.wavelength} nm)"
            )
            self._groups[name].setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)

            # layout = QtWidgets.QGridLayout()

            self._labels[f"color:{name}"] = QtWidgets.QLabel()
            self._labels[f"color:{name}"].setStyleSheet(
                f"background-color: {model_info.wavecolor}"
            )
            self._buttons[f"on:{name}"] = QtWidgets.QPushButton("ON")
            self._buttons[f"on:{name}"].setCheckable(True)

    def connection_phase(self) -> None:
        """Connect the widget."""
        ...

    def registration_phase(self) -> None:
        """Register the widget."""
        ...
