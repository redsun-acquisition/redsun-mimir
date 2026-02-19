from __future__ import annotations

from typing import TYPE_CHECKING, Any

from bluesky.protocols import Descriptor, Reading  # noqa: TC002
from qtpy import QtCore, QtWidgets
from redsun.config import ViewPositionTypes
from sunflare.log import Loggable
from sunflare.view.qt import QtView
from sunflare.virtual import Signal

from redsun_mimir.utils.descriptors import parse_key
from redsun_mimir.utils.qt import DescriptorTreeView

if TYPE_CHECKING:
    from dependency_injector.containers import DynamicContainer
    from napari.layers import Image
    from sunflare.virtual import VirtualBus

    from redsun_mimir.view._image import ImageView


class SettingsControlWidget(QtWidgets.QWidget):
    r"""Widget for controlling device settings, backed by a descriptor tree view.

    Populated once at construction from the descriptor and reading dicts
    provided by the DI container — no separate setup step required.

    Parameters
    ----------
    descriptors :
        Flat ``describe_configuration()`` dict for one or more devices,
        keyed in ``prefix:name\\property`` form.
    readings :
        Flat ``read_configuration()`` dict matching the same keys.
    layer :
        The napari image layer to attach ROI controls to.
    parent :
        Optional parent widget.
    """

    def __init__(
        self,
        descriptors: dict[str, Descriptor],
        readings: dict[str, Reading[Any]],
        layer: Image,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent=parent)

        self._layer = layer

        self.tree_view = DescriptorTreeView(descriptors, readings, self)

        self._enable_roi_button = QtWidgets.QPushButton("Toggle ROI control")
        self._enable_roi_button.setCheckable(True)
        self._full_roi_button = QtWidgets.QPushButton("Full ROI")
        self._accept_button = QtWidgets.QPushButton("Accept")
        self._full_roi_button.setEnabled(False)
        self._accept_button.setEnabled(False)
        self._enable_roi_button.toggled.connect(
            lambda checked: self._on_resize_button_toggled(checked)
        )

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.tree_view)
        layout.addWidget(self._enable_roi_button)
        layout.addWidget(self._full_roi_button)
        layout.addWidget(self._accept_button)
        self.setLayout(layout)

    def _on_resize_button_toggled(self, checked: bool) -> None:
        self._full_roi_button.setEnabled(checked)
        self._accept_button.setEnabled(checked)
        self._layer.bounding_box.visible = checked
        self._layer._overlays["roi_box"].visible = checked


class DetectorView(QtView, Loggable):
    """View for interactive detector settings control.

    Renders per-detector property panels in a tabbed widget and forwards
    user edits to the
    [`DetectorPresenter`][redsun_mimir.presenter.DetectorPresenter]
    via the virtual bus.

    Image visualisation is handled separately by
    [`ImageView`][redsun_mimir.view.ImageView]; a reference is required at
    construction so that the two views can share the same initialisation pass
    over the descriptor/reading data.

    Parameters
    ----------
    virtual_bus :
        Reference to the virtual bus.
    image_view :
        The companion [`ImageView`][redsun_mimir.view.ImageView] instance.
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

    position = ViewPositionTypes.RIGHT

    def __init__(
        self,
        virtual_bus: VirtualBus,
        /,
        image_view: ImageView,
        **kwargs: Any,
    ) -> None:
        super().__init__(virtual_bus, **kwargs)

        self._image_view = image_view

        self.settings_tab_widget = QtWidgets.QTabWidget()
        self.settings_tab_widget.setMinimumWidth(300)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        splitter.addWidget(self._image_view.viewer_window._qt_window)
        splitter.addWidget(self.settings_tab_widget)
        splitter.setSizes([750, 250])
        splitter.setChildrenCollapsible(True)

        main_layout = QtWidgets.QHBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(splitter)
        self.setLayout(main_layout)

        self.settings_controls: dict[str, SettingsControlWidget] = {}

        self.logger.info("Initialized")

        self.virtual_bus.register_signals(self)

    def inject_dependencies(self, container: DynamicContainer) -> None:
        """Inject detector configuration from the DI container."""
        descriptors: dict[str, Descriptor] = container.detector_descriptors()
        readings: dict[str, Reading[Any]] = container.detector_readings()
        self.setup_ui(descriptors, readings)

    def connect_to_virtual(self) -> None:
        """Connect to presenter signals on the virtual bus."""
        self.virtual_bus.signals["DetectorPresenter"][
            "sigConfigurationConfirmed"
        ].connect(self._handle_configuration_result)

    def setup_ui(
        self,
        descriptors: dict[str, Descriptor],
        readings: dict[str, Reading[Any]],
    ) -> None:
        r"""Initialise the settings panels and image layers.

        Groups descriptors and readings by their ``prefix:name`` device label
        (the part of the key before the backslash), then for each device:

        - adds a napari image layer via
          [`ImageView.setup_layers`][redsun_mimir.view.ImageView.setup_layers];
        - creates a [`SettingsControlWidget`][redsun_mimir.view.SettingsControlWidget]
          tab in the settings panel.

        Parameters
        ----------
        descriptors :
            Flat merged ``describe_configuration()`` output from all detectors,
            keyed as ``prefix:name\\property``.
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

            self._image_view.setup_layers(
                descriptors, readings, device_label, dev_descriptors, dev_readings
            )
            layer = self._image_view.viewer_model.layers[device_label]

            widget = SettingsControlWidget(dev_descriptors, dev_readings, layer)
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
