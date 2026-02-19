from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
from bluesky.protocols import Descriptor, Reading  # noqa: TC002
from napari.components import ViewerModel
from napari.window import Window
from qtpy import QtCore, QtWidgets
from redsun.config import ViewPositionTypes
from sunflare.log import Loggable
from sunflare.view.qt import QtView
from sunflare.virtual import Signal

from redsun_mimir.utils.descriptors import parse_key
from redsun_mimir.utils.napari import (
    ROIInteractionBoxOverlay,
    highlight_roi_box_handles,
    resize_selection_box,
)
from redsun_mimir.utils.qt import DescriptorTreeView

if TYPE_CHECKING:
    import numpy.typing as npt
    from dependency_injector.containers import DynamicContainer
    from napari.layers import Image
    from sunflare.virtual import VirtualBus


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

        self.tree_view = DescriptorTreeView(self)

        # Populate the tree once at construction
        self.tree_view.model().update_structure(descriptors)
        self.tree_view.model().update_readings(readings)

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
    """View for live image display and detector settings control.

    Renders image data forwarded by
    [`DetectorPresenter`][redsun_mimir.presenter.DetectorPresenter]
    into a napari viewer and provides per-detector settings panels
    for interactive configuration.

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
        Carries the detector name (`str`) and a mapping of the
        changed property to its new value (`dict[str, object]`).
    """

    sigPropertyChanged = Signal(str, dict[str, object])

    position = ViewPositionTypes.RIGHT

    def __init__(
        self,
        virtual_bus: VirtualBus,
        /,
        **kwargs: Any,
    ) -> None:
        super().__init__(virtual_bus, **kwargs)

        self.viewer_model = ViewerModel(
            title="Image viewer", ndisplay=2, order=(), axis_labels=()
        )

        # TODO: this should be replaced with
        # a custom viewer by using the napari
        # components rather than the
        # original napari window;
        # for now we'll go with this
        self.viewer_window = Window(
            viewer=self.viewer_model,
            show=False,
        )

        # Create a tab widget for settings controls
        self.settings_tab_widget = QtWidgets.QTabWidget()
        self.settings_tab_widget.setMinimumWidth(300)

        # Create a splitter to allow resizing between napari viewer and settings
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        splitter.addWidget(self.viewer_window._qt_window)
        splitter.addWidget(self.settings_tab_widget)
        # Set initial sizes: 75% for viewer, 25% for settings
        splitter.setSizes([750, 250])
        # Allow the splitter to be collapsed
        splitter.setChildrenCollapsible(True)

        # Create horizontal layout with the splitter
        main_layout = QtWidgets.QHBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(splitter)
        self.setLayout(main_layout)

        self.settings_controls: dict[str, SettingsControlWidget] = {}

        self.logger.info("Initialized")

        self.buffer_key = "buffer"

        self.virtual_bus.register_signals(self)

    def inject_dependencies(self, container: DynamicContainer) -> None:
        """Inject detector configuration from the DI container."""
        descriptors: dict[str, Descriptor] = container.detector_descriptors()
        readings: dict[str, Reading[Any]] = container.detector_readings()
        self.setup_ui(descriptors, readings)

    def connect_to_virtual(self) -> None:
        """Register signals and connect to virtual bus."""
        self.virtual_bus.signals["DetectorPresenter"][
            "sigConfigurationConfirmed"
        ].connect(self._handle_configuration_result)
        self.virtual_bus.signals["DetectorPresenter"]["sigNewData"].connect(
            self._update_layers, thread="main"
        )
        try:
            self.virtual_bus.signals["MedianPresenter"]["sigNewData"].connect(
                self._update_layers, thread="main"
            )
        except KeyError:
            self.logger.debug(
                "MedianPresenter not found in virtual bus; skipping median data connection."
            )

    def setup_ui(
        self,
        descriptors: dict[str, Descriptor],
        readings: dict[str, Reading[Any]],
    ) -> None:
        r"""Initialize the user interface.

        Groups descriptors and readings by their ``prefix:name`` device label
        (the part of the key before the backslash) and creates one napari
        image layer and one :class:`SettingsControlWidget` tab per device.

        Parameters
        ----------
        descriptors :
            Flat merged ``describe_configuration()`` output from all detectors,
            keyed as ``prefix:name\\property``.
        readings :
            Flat merged ``read_configuration()`` output from all detectors,
            keyed identically.
        """
        # Group keys by device name
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

            # Derive sensor shape from the first array descriptor we can find
            sensor_shape = (512, 512)
            for key, reading in dev_readings.items():
                if descriptors[key].get("dtype") == "array" and "sensor_shape" in key:
                    val = reading["value"]
                    if isinstance(val, (list, tuple)) and len(val) == 2:
                        sensor_shape = (int(val[0]), int(val[1]))
                    break

            # Infer numpy dtype from buffer descriptor if available
            dtype = "uint8"
            for key, desc in dev_descriptors.items():
                if desc.get("dtype") == "array" and "buffer" in key:
                    dtype = str(desc.get("dtype_numpy", "uint8"))
                    break

            layer = self.viewer_model.add_image(
                np.zeros(shape=sensor_shape, dtype=dtype),
                name=device_label,
            )
            layer._overlays.update(
                {
                    "roi_box": ROIInteractionBoxOverlay(
                        bounds=((0, 0), layer.data.shape), handles=True
                    )
                }
            )
            layer.mouse_drag_callbacks.append(resize_selection_box)
            layer.mouse_move_callbacks.append(highlight_roi_box_handles)

            widget = SettingsControlWidget(dev_descriptors, dev_readings, layer)
            # Forward property changes with the device label so the presenter
            # can route the set() call to the right detector instance
            widget.tree_view.model().sigPropertyChanged.connect(
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
        detector : str
            Name of the detector
        setting_name : str
            Name of the setting that was changed
        success : bool
            Whether the configuration change was successful
        """
        if detector in self.settings_controls:
            model = self.settings_controls[detector].tree_view.model()
            model.confirm_change(setting_name, success)

            if not success:
                self.logger.error(f"Failed to configure {setting_name} for {detector}")

    def _update_layers(self, data: dict[str, dict[str, Any]]) -> None:
        """Update the image layers with new data.

        Parameters
        ----------
        data: dict[str, dict[str, Any]]
            Nested dictionary where the outer key is the detector name,
            and the inner dictionary contains keys 'buffer' and 'roi'.
            'buffer' is the raw data array, and 'roi' is a 4-tuple defining
            the region of interest (x_start, x_end, y_start, y_end).
        """
        # TODO: this is very basic... needs improvement;
        # the type hint of the input should be a typed dictionary
        for obj_name, packet in data.items():
            if obj_name not in self.viewer_model.layers:
                self.logger.debug(f"Adding new layer for {obj_name}")
                buffer: npt.NDArray[Any] = packet[self.buffer_key]
                layer = self.viewer_model.add_image(
                    name=obj_name,
                    data=buffer,
                )
            else:
                layer = self.viewer_model.layers[obj_name]
                layer.data = packet[self.buffer_key]
