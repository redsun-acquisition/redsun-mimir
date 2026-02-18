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


def _get_prop(
    readings: dict[str, Reading[Any]],
    prop: str,
    default: _T,
) -> _T:
    """Find a reading value by property name suffix.

    Searches all keys whose last backslash-delimited segment matches
    *prop*, making the lookup independent of the ``prefix:name`` portion
    of the canonical ``prefix:name\\property`` key.

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
        tail = key.rsplit("\\", 1)[-1]
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
        Carries the light source name (`str`).
    sigIntensityRequest :
        Emitted when the user adjusts a light source intensity.
        Carries the light source name (`str`) and the new intensity value.
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
        (metadata) registered by [`LightPresenter.register_providers`][redsun_mimir.presenter.LightPresenter.register_providers].
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
            wavelength: int = _get_prop(readings, "wavelength", 0)
            binary: bool = _get_prop(readings, "binary", False)
            egu: str = _get_prop(readings, "egu", "")
            intensity_range: list[int | float] = _get_prop(
                readings, "intensity_range", [0, 100]
            )
            step_size: int | float = _get_prop(readings, "step_size", 1)

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

        self.virtual_bus.register_signals(self)

    def connect_to_virtual(self) -> None:
        """Register signals and connect to virtual bus."""

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
