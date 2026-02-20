from __future__ import annotations

from typing import TYPE_CHECKING, Any

from bluesky.protocols import Descriptor, Reading  # noqa: TC002
from qtpy import QtWidgets
from sunflare.log import Loggable
from sunflare.view import ViewPosition
from sunflare.view.qt import QtView
from sunflare.virtual import Signal

from redsun_mimir.utils.descriptors import parse_key
from redsun_mimir.utils.qt import DescriptorTreeView

if TYPE_CHECKING:
    from sunflare.virtual import VirtualContainer


class SettingsControlWidget(QtWidgets.QWidget):
    r"""Widget for controlling device settings, backed by a descriptor tree view.

    Populated once at construction from the descriptor and reading dicts
    provided by the DI container — no separate setup step required.

    Parameters
    ----------
    descriptors :
        Flat ``describe_configuration()`` dict for one device,
        keyed in ``prefix:name-property`` form.
    readings :
        Flat ``read_configuration()`` dict matching the same keys.
    parent :
        Optional parent widget.

    Note
    ----
    The ROI control buttons are present but currently non-functional.
    Full ROI wiring (toggling napari overlay visibility) will be
    implemented in a follow-up task once the ROI signal is published
    on the virtual bus by
    [`ImageView`][redsun_mimir.view.ImageView].
    """

    def __init__(
        self,
        descriptors: dict[str, Descriptor],
        readings: dict[str, Reading[Any]],
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent=parent)

        self.tree_view = DescriptorTreeView(descriptors, readings, self)

        self._enable_roi_button = QtWidgets.QPushButton("Toggle ROI control")
        self._enable_roi_button.setCheckable(True)
        self._full_roi_button = QtWidgets.QPushButton("Full ROI")
        self._accept_button = QtWidgets.QPushButton("Accept")
        self._full_roi_button.setEnabled(False)
        self._accept_button.setEnabled(False)
        self._enable_roi_button.toggled.connect(self._on_resize_button_toggled)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.tree_view)
        layout.addWidget(self._enable_roi_button)
        layout.addWidget(self._full_roi_button)
        layout.addWidget(self._accept_button)
        self.setLayout(layout)

    def _on_resize_button_toggled(self, checked: bool) -> None:
        self._full_roi_button.setEnabled(checked)
        self._accept_button.setEnabled(checked)


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
    virtual_bus :
        Reference to the virtual bus.
    **kwargs :
        Additional keyword arguments passed to the parent view.

    Attributes
    ----------
    sigPropertyChanged :
        Emitted when the user changes a detector property.
        Carries the detector name (`str`) and a mapping of the changed
        property to its new value (`dict[str, object]`).
    """

    sigPropertyChanged = Signal(str, dict[str, object])

    position = ViewPosition.RIGHT

    def __init__(
        self,
        name: str,
        /,
        **kwargs: Any,
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
        if "DetectorPresenter" in container.signals:
            container.signals["DetectorPresenter"]["sigConfigurationConfirmed"].connect(
                self._handle_configuration_result
            )

    def setup_ui(
        self,
        descriptors: dict[str, Descriptor],
        readings: dict[str, Reading[Any]],
    ) -> None:
        r"""Initialise the settings panels.

        Groups descriptors and readings by their ``prefix:name`` device label
        (the part of the key before the backslash) and creates one
        [`SettingsControlWidget`][redsun_mimir.view.SettingsControlWidget]
        tab per device.

        Parameters
        ----------
        descriptors :
            Flat merged ``describe_configuration()`` output from all detectors,
            keyed as ``prefix:name-property``.
        readings :
            Flat merged ``read_configuration()`` output from all detectors,
            keyed identically.
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
            widget.tree_view.sigPropertyChanged.connect(
                lambda setting, value, lbl=device_label: self.sigPropertyChanged.emit(
                    lbl, {setting: value}
                )
            )
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
