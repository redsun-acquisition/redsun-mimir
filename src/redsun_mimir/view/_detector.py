from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
from bluesky.protocols import Descriptor  # noqa: TC002
from napari.components import ViewerModel
from napari.window import Window
from qtpy import QtCore, QtWidgets
from redsun.config import ViewPositionTypes
from sunflare.log import Loggable
from sunflare.view.qt import QtView
from sunflare.virtual import Signal

from redsun_mimir.common import ConfigurationDict  # noqa: TC001
from redsun_mimir.protocols import DetectorProtocol  # noqa: TC001
from redsun_mimir.utils.napari import (
    ROIInteractionBoxOverlay,
    highlight_roi_box_handles,
    resize_selection_box,
)
from redsun_mimir.utils.qt import DescriptorTreeView

if TYPE_CHECKING:
    from typing import Any

    import numpy.typing as npt
    from dependency_injector.containers import DynamicContainer
    from napari.layers import Image
    from sunflare.virtual import VirtualBus


class SettingsControlWidget(QtWidgets.QWidget):
    """Widget for controlling the detector settings.

    Parameters
    ----------
    layer : ``Image``
        The image layer to control.
    parent: ``QtWidgets.QWidget``, optional
        The parent widget for this control widget. Defaults to None.
    """

    def __init__(self, layer: Image, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent=parent)

        self._layer = layer

        self.tree_view = DescriptorTreeView(self)
        self.tree_view.model().sigStructureChanged.connect(self._on_structure_changed)

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

    def _on_structure_changed(self) -> None:
        self.tree_view.expandAll()
        for i in range(self.tree_view.model().columnCount()):
            self.tree_view.resizeColumnToContents(i)


class DetectorWidget(QtView, Loggable):
    """Widget for rendering acquired image data and control detector settings.

    Parameters
    ----------
    virtual_bus : ``VirtualBus``
        Reference to the virtual bus.
    **kwargs : ``Any``
        Additional keyword arguments.

    Attributes
    ----------
    sigPropertyChanged : ``Signal[str, dict[str, object]]``
        Signal emitted when a property of a detector is changed.
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

    def inject_dependencies(self, container: DynamicContainer) -> None:
        """Inject detector info and configuration from the DI container."""
        models_info: dict[str, DetectorProtocol] = container.detector_models()
        model_config: ConfigurationDict = container.detector_configuration()
        model_reading: dict[str, dict[str, Descriptor]] = (
            container.detector_descriptions()
        )
        self.setup_ui(models_info, model_config, model_reading)

    def connect_to_virtual(self) -> None:
        """Register signals and connect to virtual bus."""
        self.virtual_bus.register_signals(self)
        self.virtual_bus.signals["DetectorController"][
            "sigConfigurationConfirmed"
        ].connect(self._handle_configuration_result)
        self.virtual_bus.signals["DetectorController"]["sigNewData"].connect(
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
        models_info: dict[str, DetectorProtocol],
        model_config: ConfigurationDict,
        model_reading: dict[str, dict[str, Descriptor]],
    ) -> None:
        """Initialize the user interface.

        Parameters
        ----------
        models_info : ``dict[str, DetectorProtocol]``
            Mapping of detector names to their device instances.
        model_config : ``ConfigurationDict``
            Configuration data from the presenter.
        model_reading : ``dict[str, dict[str, Descriptor]]``
            Reading description data from the presenter.
        """
        self._detectors_info = models_info

        for detector, info in self._detectors_info.items():
            config_descriptor = model_config["descriptors"][detector]
            config_reading = model_config["readings"][detector]
            dtype = model_reading[detector][f"{detector}:buffer"].get(
                "dtype_numpy", "uint8"
            )

            layer = self.viewer_model.add_image(
                np.zeros(shape=info.sensor_shape, dtype=dtype),
                name=detector,
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
            self.settings_controls[detector] = SettingsControlWidget(layer)
            self.settings_controls[detector].tree_view.model().update_structure(
                config_descriptor
            )
            self.settings_controls[detector].tree_view.model().update_readings(
                config_reading
            )
            # Capture detector name by value using default argument to avoid closure issue
            self.settings_controls[
                detector
            ].tree_view.model().sigPropertyChanged.connect(
                lambda setting, value, det=detector: self.sigPropertyChanged.emit(
                    det, {setting: value}
                )
            )

            self.settings_tab_widget.addTab(
                self.settings_controls[detector],
                f"{detector}",
            )

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
