from __future__ import annotations

from typing import TYPE_CHECKING, Any

from bluesky.protocols import Descriptor, Reading  # noqa: TC002
from qtpy import QtWidgets
from redsun.log import Loggable
from redsun.utils import find_signals
from redsun.utils.descriptors import parse_key
from redsun.view import ViewPosition
from redsun.view.qt import QtView
from redsun.view.qt.treeview import DescriptorTreeView
from redsun.virtual import Signal

if TYPE_CHECKING:
    from redsun.virtual import VirtualContainer


class SettingsControlWidget(QtWidgets.QWidget):
    """Widget for controlling device settings, backed by a descriptor tree view.

    Parameters
    ----------
    descriptors : dict[str, Descriptor]
        Detector output of "describe()".
    readings : dict[str, Reading[Any]]
        Detector output of "read()".
    parent : QtWidgets.QWidget | None, optional
        Optional parent widget.
    """

    def __init__(
        self,
        descriptors: dict[str, Descriptor],
        readings: dict[str, Reading[Any]],
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent=parent)

        self.tree_view = DescriptorTreeView(descriptors, readings, parent=self)
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.tree_view)
        self.setLayout(layout)


class DetectorView(QtView, Loggable):
    """View for interactive detector settings control.

    Renders per-detector property panels in a tabbed widget and forwards
    user edits to the
    [`DetectorPresenter`][redsun_mimir.presenter.DetectorPresenter]
    via the virtual bus.

    Image visualisation is handled independently by
    [`ImageView`][redsun_mimir.view.ImageView]; the two views share only
    the virtual bus and do not hold references to each other.

    Parameters
    ----------
    name: str
        Identity key of the view.

    Attributes
    ----------
    sigPropertyChanged : Signal[str, str, Any]
        Emitted when the user changes a detector property.
        - str: The detector name.
        - str: The property name.
        - Any: The new value of the property.
    """

    sigPropertyChanged = Signal(str, str, object)

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

        self.settings_tab_widget = QtWidgets.QTabWidget()
        self.settings_tab_widget.setMinimumWidth(300)

        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.settings_tab_widget)
        self.setLayout(layout)

        self.settings_controls: dict[str, SettingsControlWidget] = {}

        self.logger.info("Initialized")

    def register_providers(self, container: VirtualContainer) -> None:
        """Register detector view signals in the virtual container."""
        container.register_signals(self)

    def inject_dependencies(self, container: VirtualContainer) -> None:
        """Inject detector configuration from the DI container."""
        descriptors: dict[str, Descriptor] = container.detector_descriptors()
        readings: dict[str, Reading[Any]] = container.detector_readings()
        self.setup_ui(descriptors, readings)
        sigs = find_signals(container, ["sigConfigurationConfirmed"])
        if "sigConfigurationConfirmed" in sigs:
            sigs["sigConfigurationConfirmed"].connect(self._handle_configuration_result)

    def setup_ui(
        self,
        descriptors: dict[str, Descriptor],
        readings: dict[str, Reading[Any]],
    ) -> None:
        r"""Initialise the settings panels.

        Parameters
        ----------
        descriptors : dict[str, Descriptor]
            Flat merged ``describe()`` output from all detectors, keyed identically.
        readings : dict[str, Reading[Any]]
            Flat merged ``read()`` output from all detectors, keyed identically.
        """
        devices: dict[str, dict[str, Descriptor]] = {}
        for key, descriptor in descriptors.items():
            try:
                name, _ = parse_key(key)
            except ValueError:
                self.logger.warning(f"Skipping malformed descriptor key: {key!r}")
                continue
            devices.setdefault(name, {})[key] = descriptor

        for device_label, dev_descriptors in devices.items():
            dev_readings = {k: v for k, v in readings.items() if k in dev_descriptors}

            widget = SettingsControlWidget(dev_descriptors, dev_readings, self)
            widget.tree_view.sigPropertyChanged.connect(self.sigPropertyChanged)
            self.settings_controls[device_label] = widget
            self.settings_tab_widget.addTab(widget, device_label)

    def _handle_configuration_result(
        self, detector: str, setting_name: str, success: bool
    ) -> None:
        """Handle the result of a configuration change.

        Parameters
        ----------
        detector :
            Name of the detector.
        setting_name :
            Name of the setting that was attempted.
        success :
            Whether the change was applied successfully.
        """
        if detector in self.settings_controls:
            self.settings_controls[detector].tree_view.confirm_change(
                setting_name, success
            )
            if not success:
                self.logger.error(f"Failed to configure {setting_name} for {detector}")
