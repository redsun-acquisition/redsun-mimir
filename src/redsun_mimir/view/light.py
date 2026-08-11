"""View for light source control with per-channel support."""

from __future__ import annotations

import re
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

_KEY_GROUP = "{label}"
_KEY_BUTTON_ON = "on:{label}"
_KEY_SLIDER_POWER = "power:{label}"
_KEY_LABEL_EGU = "egu:{label}"
_KEY_CH_ENABLE = "ch_enable:{label}:{ch}"
_KEY_CH_SLIDER = "ch_slider:{label}:{ch}"


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

    Builds one control group per light device.  Devices with
    per-channel signals (e.g. ``Cyan_Level``, ``Red_Enable``)
    get additional channel sliders and checkboxes.

    Parameters
    ----------
    name: str
        Identity key of the view.

    Attributes
    ----------
    sigToggleLightRequest : Signal[str]
        Emitted when the user toggles a light source on or off.
    sigIntensityRequest : Signal[str, Any]
        Emitted when the user adjusts a light source intensity.
    sigChannelEnableRequest : Signal[str, str, str]
        Emitted when the user toggles a channel on/off.
        Carries device label, channel name, and new value (``"0"``
        or ``"1"``).
    sigChannelLevelRequest : Signal[str, str, int]
        Emitted when the user adjusts a channel power level.
        Carries device label, channel name, and new level.
    """

    sigToggleLightRequest = Signal(str)
    sigIntensityRequest = Signal(str, object)
    sigChannelEnableRequest = Signal(str, str, str)
    sigChannelLevelRequest = Signal(str, str, int)

    _CHANNEL_LEVEL_RE = re.compile(r"^(.+)_level$", re.IGNORECASE)

    @property
    def view_position(self) -> ViewPosition:
        return ViewPosition.RIGHT

    def __init__(self, name: str, /) -> None:
        super().__init__(name)
        self._configuration: dict[str, Reading[Any]] = {}
        self._description: dict[str, Descriptor] = {}
        self.setWindowTitle("Light sources")

        self.main_layout = QtWidgets.QVBoxLayout()
        self._labels: dict[str, QtWidgets.QLabel] = {}
        self._buttons: dict[str, QtWidgets.QPushButton] = {}
        self._checkboxes: dict[str, QtWidgets.QCheckBox] = {}
        self._sliders: dict[str, QLabeledDoubleSlider | QLabeledSlider] = {}
        self._groups: dict[str, QtWidgets.QGroupBox] = {}

        float_regex = QtCore.QRegularExpression(r"^[-+]?\d*\.?\d+$")
        self.validator = QtGui.QRegularExpressionValidator(float_regex)

    def register_providers(self, container: VirtualContainer) -> None:
        container.register_signals(self)

    def inject_dependencies(self, container: VirtualContainer) -> None:
        configuration: dict[str, Reading[Any]] = container.light_configuration()
        description: dict[str, Descriptor] = container.light_description()
        self.setup_ui(configuration, description)

    @staticmethod
    def _discover_channels(props: list[str]) -> list[str]:
        channels: list[str] = []
        for p in props:
            m = LightView._CHANNEL_LEVEL_RE.match(p)
            if m:
                channels.append(m.group(1))
        return sorted(set(channels))

    def setup_ui(
        self,
        readings: dict[str, Reading[Any]],
        description: dict[str, Descriptor],
    ) -> None:
        reading_names: dict[str, list[str]] = {}
        for key in readings.keys():
            name, prop = parse_key(key)
            reading_names.setdefault(name, []).append(prop)

        for name, props in reading_names.items():
            layout = QtWidgets.QGridLayout()
            wavelength_val: Any = "?"
            if "wavelength" in props:
                wavelength_val = readings.get(
                    f"{name}-wavelength", {"value": "?"}
                )["value"]
            units = description.get(
                f"{name}-intensity", {}
            ).get("units", "NA")

            self._groups[_group_key(name)] = QtWidgets.QGroupBox(
                f"{name} ({wavelength_val} nm)"
            )
            self._groups[_group_key(name)].setAlignment(
                QtCore.Qt.AlignmentFlag.AlignHCenter
                | QtCore.Qt.AlignmentFlag.AlignRight
            )
            self._groups[_group_key(name)].setLayout(layout)

            # --- master toggle button ---
            self._buttons[_button_on_key(name)] = QtWidgets.QPushButton("ON")
            self._buttons[_button_on_key(name)].setCheckable(True)
            self._buttons[_button_on_key(name)].clicked.connect(
                lambda _, lbl=name: self._on_toggle_button_checked(lbl)
            )

            # --- master intensity slider ---
            dtype = description.get(f"{name}-intensity", {}).get("dtype", "number")
            limits = description.get(f"{name}-intensity", {}).get("limits")
            low: float | None = None
            high: float | None = None
            if limits and limits.get("control"):
                ctrl = limits["control"]
                low = ctrl.get("low")
                high = ctrl.get("high")
            if dtype == "integer":
                slider: QLabeledDoubleSlider | QLabeledSlider = QLabeledSlider(
                    QtCore.Qt.Orientation.Horizontal
                )
                slider_range = [low or 0, high or 100]
            else:
                slider = QLabeledDoubleSlider(QtCore.Qt.Orientation.Horizontal)
                slider_range = [low or 0.0, high or 100.0]
            self._sliders[_slider_power_key(name)] = slider
            slider.setRange(*slider_range)
            slider.valueChanged.connect(
                lambda value, lbl=name: self._on_slider_changed(value, lbl)
            )
            self._labels[_label_egu_key(name)] = QtWidgets.QLabel(units)

            row = 0
            layout.addWidget(self._buttons[_button_on_key(name)], row, 0)
            layout.addWidget(self._sliders[_slider_power_key(name)], row, 1, 1, 3)
            layout.addWidget(self._labels[_label_egu_key(name)], row, 4)

            # --- per-channel controls ---
            channels = self._discover_channels(props)
            for ch in channels:
                row += 1
                enable_key = f"{name}-{ch}_enable"
                level_key = f"{name}-{ch}_level"

                cb = QtWidgets.QCheckBox(ch)
                cb.setChecked(
                    str(readings.get(enable_key, {}).get("value", "0")) == "1"
                )
                cb.toggled.connect(
                    lambda checked, lbl=name, cn=ch: self._on_channel_toggled(
                        checked, lbl, cn
                    )
                )
                self._checkboxes[_KEY_CH_ENABLE.format(label=name, ch=ch)] = cb

                ch_slider: QLabeledDoubleSlider | QLabeledSlider
                ch_desc = description.get(level_key, {})
                ch_dtype = ch_desc.get("dtype", "integer")
                ch_limits = ch_desc.get("limits")
                ch_low: float | None = None
                ch_high: float | None = None
                if ch_limits and ch_limits.get("control"):
                    ctrl = ch_limits["control"]
                    ch_low = ctrl.get("low")
                    ch_high = ctrl.get("high")
                if ch_dtype == "number":
                    ch_slider = QLabeledDoubleSlider(QtCore.Qt.Orientation.Horizontal)
                    ch_range = [ch_low or 0.0, ch_high or 100.0]
                else:
                    ch_slider = QLabeledSlider(QtCore.Qt.Orientation.Horizontal)
                    ch_range = [int(ch_low or 0), int(ch_high or 100)]
                ch_val = readings.get(level_key, {}).get("value", 0)
                ch_slider.setRange(*ch_range)
                ch_slider.setValue(int(ch_val) if isinstance(ch_val, (int, float)) else 0)
                ch_slider.valueChanged.connect(
                    lambda value, lbl=name, cn=ch: self._on_channel_level_changed(
                        int(value), lbl, cn
                    )
                )
                ch_key = _KEY_CH_SLIDER.format(label=name, ch=ch)
                self._sliders[ch_key] = ch_slider

                layout.addWidget(cb, row, 0)
                layout.addWidget(ch_slider, row, 1, 1, 3)

            self._groups[_group_key(name)].setLayout(layout)
            self.main_layout.addWidget(self._groups[_group_key(name)])

        self.setLayout(self.main_layout)

    def _on_toggle_button_checked(self, device_label: str) -> None:
        self.sigToggleLightRequest.emit(device_label)
        btn = self._buttons[_button_on_key(device_label)]
        btn.setText("OFF" if btn.isChecked() else "ON")

    def _on_slider_changed(self, value: int | float, device_label: str) -> None:
        self.logger.debug(
            f"Change intensity of {device_label} to {float(value):.2f}"
        )
        self.sigIntensityRequest.emit(device_label, value)

    def _on_channel_toggled(
        self, checked: bool, device_label: str, channel: str
    ) -> None:
        val = "1" if checked else "0"
        self.logger.debug(f"Toggle {device_label} {channel} -> {val}")
        self.sigChannelEnableRequest.emit(device_label, channel, val)

    def _on_channel_level_changed(
        self, value: int, device_label: str, channel: str
    ) -> None:
        self.logger.debug(f"Set {device_label} {channel} level -> {value}")
        self.sigChannelLevelRequest.emit(device_label, channel, value)
