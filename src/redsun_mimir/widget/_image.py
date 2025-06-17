from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
from napari.components import ViewerModel
from napari.window import Window
from qtpy import QtWidgets
from sunflare.log import Loggable
from sunflare.view.qt import BaseQtWidget
from sunflare.virtual import Signal

from redsun_mimir.model import DetectorModelInfo
from redsun_mimir.utils.napari import (
    ROIInteractionBoxOverlay,
    highlight_roi_box_handles,
    resize_selection_box,
)
from redsun_mimir.utils.qt import DescriptorTreeView

if TYPE_CHECKING:
    from typing import Any

    from bluesky.protocols import Descriptor, Reading
    from napari.layers import Image
    from sunflare.config import RedSunSessionInfo
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


class ImageWidget(BaseQtWidget, Loggable):
    """Widget for rendering acquired image data and control detector settings.

    Parameters
    ----------
    config : ``RedSunSessionInfo``
        Configuration information for the session.
    virtual_bus : ``VirtualBus``
        Reference to the virtual bus.
    *args : ``Any``
        Additional positional arguments.
    **kwargs : ``Any``
        Additional keyword arguments.
    """

    sigConfigRequest = Signal()
    sigPropertyChanged = Signal(str, dict[str, object])

    def __init__(
        self,
        config: RedSunSessionInfo,
        virtual_bus: VirtualBus,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            config,
            virtual_bus,
            *args,
            **kwargs,
        )

        self.detectors_info = {
            name: model_info
            for name, model_info in self.config.models.items()
            if isinstance(model_info, DetectorModelInfo)
        }

        self.viewer_model = ViewerModel(
            title="Image viewer", ndisplay=2, order=(), axis_labels=()
        )
        self.viewer_window = Window(
            viewer=self.viewer_model,
            show=False,
        )

        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.viewer_window._qt_window)
        self.setLayout(layout)

        self.settings_controls: dict[str, SettingsControlWidget] = {}

    def registration_phase(self) -> None:
        self.virtual_bus.register_signals(self)

    def connection_phase(self) -> None:
        self.virtual_bus["ImageController"]["sigNewDetectorDescriptor"].connect(
            self._update_detectors_listing
        )
        self.virtual_bus["ImageController"]["sigNewDetectorDescriptorReading"].connect(
            self._update_parameter
        )
        # Add confirmation signal connection
        self.virtual_bus["ImageController"]["sigConfigurationConfirmed"].connect(
            self._handle_configuration_result
        )
        self.sigConfigRequest.emit()

    def _update_detectors_listing(
        self, detector: str, descriptor: dict[str, Descriptor]
    ) -> None:
        """Update the detector listing in the viewer.

        Parameters
        ----------
        detector : ``str``
            The name of the detector.
        descriptor : ``dict[str, Descriptor]``
            The descriptor containing information about the detectors.
        """
        # TODO: dtype should be provided either from the descriptor or from the model info
        layer = self.viewer_model.add_image(
            np.zeros(shape=self.detectors_info[detector].sensor_shape, dtype=np.uint8),
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
        self.settings_controls[detector].tree_view.model().update_structure(descriptor)
        self.settings_controls[detector].tree_view.model().sigPropertyChanged.connect(
            lambda setting, value: self.sigPropertyChanged.emit(
                detector, {setting: value}
            )
        )

        self.viewer_window.add_dock_widget(
            self.settings_controls[detector],
            name=f"{detector}",
            allowed_areas=["right"],
            area="right",
            tabify=True,
        )

    def _update_parameter(
        self, detector: str, reading: dict[str, Reading[Any]]
    ) -> None:
        """Update the parameters of a detector.

        Parameters
        ----------
        detector : ``str``
            The name of the detector.
        reading : ``dict[str, Reading[Any]]``
            The reading containing the updated parameters.
        """
        self.settings_controls[detector].tree_view.model().update_readings(reading)

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
                # Optionally show a warning to the user
                self.logger.warning(
                    f"Failed to configure {setting_name} for {detector}"
                )
