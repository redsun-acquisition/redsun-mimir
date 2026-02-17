from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar, cast

from qtpy import QtCore, QtGui, QtWidgets
from redsun.config import ViewPositionTypes
from sunflare.log import Loggable
from sunflare.view.qt import QtView
from sunflare.virtual import Signal
from superqt import QLabeledDoubleSlider, QLabeledSlider

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


class LightWidget(QtView, Loggable):
    """Light source widget for Redsun Mimir.

    Parameters
    ----------
    virtual_bus : ``VirtualBus``
        Virtual bus for the session.

    Attributes
    ----------
    sigToggleLightRequest : ``Signal[str]``
        Signal emitted when the user toggles a light source on or off.
        - ``str``: light source name
    sigIntensityRequest : ``Signal[str, object]``
        Signal emitted when the user changes the intensity of a light source.
        - ``str``: light source name
        - ``object``: new intensity value

    """

    sigToggleLightRequest = Signal(str)
    sigIntensityRequest = Signal(str, object)  # name, intensity

    position = ViewPositionTypes.CENTER

    def __init__(
        self,
        virtual_bus: VirtualBus,
        /,
        **kwargs: Any,
    ) -> None:
        super().__init__(virtual_bus, **kwargs)

        self._configuration: dict[str, dict[str, Reading[Any]]] = {}
        self._description: dict[str, dict[str, Descriptor]] = {}
        self.setWindowTitle("Light sources")

        self.main_layout = QtWidgets.QVBoxLayout()

        self._labels: dict[str, QtWidgets.QLabel] = {}
        self._buttons: dict[str, QtWidgets.QPushButton] = {}
        self._sliders: dict[str, QLabeledDoubleSlider | QLabeledSlider] = {}
        self._groups: dict[str, QtWidgets.QGroupBox] = {}

        # Regular expression for a valid floating-point number
        float_regex = QtCore.QRegularExpression(r"^[-+]?\d*\.?\d+$")
        self.validator = QtGui.QRegularExpressionValidator(float_regex)

    def inject_dependencies(self, container: DynamicContainer) -> None:
        """Inject light configuration from the DI container and build the UI.

        Retrieves configuration readings (current values) and descriptors
        (metadata) registered by ``LightController.register_providers``.
        """
        configuration: dict[str, dict[str, Reading[Any]]] = (
            container.light_configuration()
        )
        description: dict[str, dict[str, Descriptor]] = container.light_description()
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
            Mapping of light names to their current configuration readings.
            Each inner dict maps ``"<light>:<key>"`` strings to Reading dicts.
        description : ``dict[str, dict[str, Descriptor]]``
            Mapping of light names to their configuration descriptors.
            Each inner dict maps ``"<light>:<key>"`` strings to Descriptor dicts.
        """
        self._configuration = configuration
        self._description = description

        for name, readings in configuration.items():
            wavelength: int = _get_value(readings, f"{name}:wavelength", 0)
            binary: bool = _get_value(readings, f"{name}:binary", False)
            egu: str = _get_value(readings, f"{name}:egu", "")
            intensity_range: list[int | float] = _get_value(
                readings, f"{name}:intensity_range", [0, 100]
            )
            step_size: int | float = _get_value(readings, f"{name}:step_size", 1)

            self._groups[name] = QtWidgets.QGroupBox(f"{name} ({wavelength} nm)")
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

            if not binary:
                slider: QLabeledDoubleSlider | QLabeledSlider
                if all(isinstance(i, int) for i in intensity_range):
                    slider = QLabeledSlider()
                elif all(isinstance(i, float) for i in intensity_range):
                    slider = QLabeledDoubleSlider()
                else:
                    # should never happen
                    raise TypeError(
                        "Intensity range must be either all integers or all floats."
                    )
                self._sliders[f"power:{name}"] = slider
                self._sliders[f"power:{name}"].setOrientation(
                    QtCore.Qt.Orientation.Horizontal
                )
                self._sliders[f"power:{name}"].setRange(*intensity_range)
                self._sliders[f"power:{name}"].setSingleStep(int(step_size))
                self._sliders[f"power:{name}"].valueChanged.connect(
                    lambda value, name=name: self._on_slider_changed(value, name)
                )
                self._sliders[f"power:{name}"]._label.setAlignment(
                    QtCore.Qt.AlignmentFlag.AlignHCenter
                )
                self._labels[f"egu:{name}"] = QtWidgets.QLabel(egu)
                layout.addWidget(self._buttons[f"on:{name}"], 0, 0)
                layout.addWidget(self._sliders[f"power:{name}"], 0, 1, 1, 3)
                layout.addWidget(self._labels[f"egu:{name}"], 0, 4)
            else:
                layout.addWidget(self._buttons[f"on:{name}"], 0, 0, 1, 4)

            self._groups[name].setLayout(layout)
            self.main_layout.addWidget(self._groups[name])

        self.setLayout(self.main_layout)

    def connect_to_virtual(self) -> None:
        """Register signals and connect to virtual bus."""
        self.virtual_bus.register_signals(self)

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
