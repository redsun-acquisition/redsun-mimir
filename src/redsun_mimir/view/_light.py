from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar, cast

from qtpy import QtCore, QtGui, QtWidgets
from sunflare.log import Loggable
from sunflare.view import ViewPosition
from sunflare.view.qt import QtView
from sunflare.virtual import Signal
from superqt import QLabeledDoubleSlider, QLabeledSlider

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

    Searches all keys whose last ``-``-delimited segment matches *prop*,
    making the lookup independent of the ``prefix:name`` portion
    of the canonical ``name-property`` key.

    Parameters
    ----------
    readings :
        Inner per-device reading dict (values from ``read_configuration()``).
    prop :
        Property name to match (e.g. ``"binary"``, ``"wavelength"``).
    default :
        Returned when no matching key is found.
    """
    for key, reading in readings.items():
        tail = key.rsplit("-", 1)[-1]
        if tail == prop:
            return cast("_T", reading["value"])
    return default


class LightView(QtView, Loggable):
    """View for light source toggle and intensity control.

    Builds one control group per light device using configuration
    provided by [`LightPresenter`][redsun_mimir.presenter.LightPresenter].

    Parameters
    ----------
    virtual_bus :
        Virtual bus for the session.

    Attributes
    ----------
    sigToggleLightRequest :
        Emitted when the user toggles a light source on or off.
        Carries the light source device label (``str``, ``prefix:name``).
    sigIntensityRequest :
        Emitted when the user adjusts a light source intensity.
        Carries the light source device label (``str``) and the new
        intensity value.
    r
    """

    sigToggleLightRequest = Signal(str)
    sigIntensityRequest = Signal(str, object)  # device_label, intensity

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
        configuration: dict[str, Reading[Any]] = container.light_configuration()
        description: dict[str, Descriptor] = container.light_description()
        self.setup_ui(configuration, description)
        container.register_signals(self)

    def inject_dependencies(self, container: VirtualContainer) -> None:
        """Connect inbound signals from the light presenter."""
        pass  # LightPresenter has no feedback signals back to LightView currently

    def setup_ui(
        self,
        configuration: dict[str, Reading[Any]],
        description: dict[str, Descriptor],
    ) -> None:
        r"""Build the UI from configuration readings and descriptors.

        Parameters
        ----------
        configuration : ``dict[str, Reading[Any]]``
            Flat mapping of canonical ``prefix:name\property`` keys to readings,
            merging all light devices.
        description : ``dict[str, Descriptor]``
            Flat mapping of canonical ``prefix:name\property`` keys to
            descriptors, merging all light devices.
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

        for device_label, readings in devices.items():
            wavelength: int = _get_prop(readings, "wavelength", 0)
            binary: bool = _get_prop(readings, "binary", False)
            egu: str = _get_prop(readings, "egu", "")
            intensity_range: list[int | float] = _get_prop(
                readings, "intensity_range", [0, 100]
            )
            step_size: int | float = _get_prop(readings, "step_size", 1)

            self._groups[device_label] = QtWidgets.QGroupBox(
                f"{device_label} ({wavelength} nm)"
            )
            self._groups[device_label].setAlignment(
                QtCore.Qt.AlignmentFlag.AlignHCenter
                | QtCore.Qt.AlignmentFlag.AlignRight
            )

            layout = QtWidgets.QGridLayout()

            self._buttons[f"on:{device_label}"] = QtWidgets.QPushButton("ON")
            self._buttons[f"on:{device_label}"].setCheckable(True)
            self._buttons[f"on:{device_label}"].clicked.connect(
                lambda _, lbl=device_label: self._on_toggle_button_checked(lbl)
            )

            if not binary:
                slider: QLabeledDoubleSlider | QLabeledSlider
                if all(isinstance(i, int) for i in intensity_range):
                    slider = QLabeledSlider()
                elif all(isinstance(i, float) for i in intensity_range):
                    slider = QLabeledDoubleSlider()
                else:
                    raise TypeError(
                        "Intensity range must be either all integers or all floats."
                    )
                self._sliders[f"power:{device_label}"] = slider
                self._sliders[f"power:{device_label}"].setOrientation(
                    QtCore.Qt.Orientation.Horizontal
                )
                self._sliders[f"power:{device_label}"].setRange(*intensity_range)
                self._sliders[f"power:{device_label}"].setSingleStep(int(step_size))
                self._sliders[f"power:{device_label}"].valueChanged.connect(
                    lambda value, lbl=device_label: self._on_slider_changed(value, lbl)
                )
                self._sliders[f"power:{device_label}"]._label.setAlignment(
                    QtCore.Qt.AlignmentFlag.AlignHCenter
                )
                self._labels[f"egu:{device_label}"] = QtWidgets.QLabel(egu)
                layout.addWidget(self._buttons[f"on:{device_label}"], 0, 0)
                layout.addWidget(self._sliders[f"power:{device_label}"], 0, 1, 1, 3)
                layout.addWidget(self._labels[f"egu:{device_label}"], 0, 4)
            else:
                layout.addWidget(self._buttons[f"on:{device_label}"], 0, 0, 1, 4)

            self._groups[device_label].setLayout(layout)
            self.main_layout.addWidget(self._groups[device_label])

        self.setLayout(self.main_layout)

    def _on_toggle_button_checked(self, device_label: str) -> None:
        """Toggle the light source."""
        self.sigToggleLightRequest.emit(device_label)
        if self._buttons[f"on:{device_label}"].isChecked():
            self._buttons[f"on:{device_label}"].setText("OFF")
        else:
            self._buttons[f"on:{device_label}"].setText("ON")

    def _on_slider_changed(self, value: int | float, device_label: str) -> None:
        """Change the intensity of the light source."""
        self.logger.debug(
            f"Change intensity of light source {device_label} to {value:.2f}"
        )
        self.sigIntensityRequest.emit(device_label, value)
