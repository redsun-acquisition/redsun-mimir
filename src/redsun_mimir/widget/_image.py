from __future__ import annotations

from typing import TYPE_CHECKING

from napari.components import ViewerModel
from napari.window import Window
from qtpy import QtWidgets
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

    import numpy.typing as npt
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

    Attributes
    ----------
    sigFullROIRequest : Signal
        Signal emitted when the full ROI is requested.
    sigNewROIRequest : Signal(int, int, int, int)
        Signal emitted when a new ROI is requested; emits
        the following parameters:
        - dx: x-coordinate of the top-left corner of the ROI
        - dy: y-coordinate of the top-left corner of the ROI
        - width: width of the ROI
        - height: height of the ROI
    """

    sigConfigRequest = Signal()
    sigPropertyChanged = Signal(str, dict[str, object])

    def __init__(self, layer: Image, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent=parent)

        self._layer = layer

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
        layout.addWidget(self._enable_roi_button)
        layout.addWidget(self._full_roi_button)
        layout.addWidget(self._accept_button)
        self.setLayout(layout)

    def _on_resize_button_toggled(self, checked: bool) -> None:
        self._full_roi_button.setEnabled(checked)
        self._accept_button.setEnabled(checked)
        self._layer.bounding_box.visible = checked
        self._layer._overlays["roi_box"].visible = checked


class ImageWidget(BaseQtWidget):
    """Image widget for displaying images.

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
        self.settings_tree_view = DescriptorTreeView(self)
        self.settings_tree_view.model().sigStructureChanged.connect(
            self._on_structure_changed
        )
        self.settings_tree_view.model().sigPropertyChanged.connect(
            self.sigPropertyChanged
        )

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

        # keep a reference to the subcomponents of the viewer
        # for later use and easier access
        self._layer_list = self.viewer_window._qt_viewer.layers
        self._layer_controls = self.viewer_window._qt_viewer.controls

        self._roi_controls: dict[Image, SettingsControlWidget] = {}

    def add_detector(self, data: npt.NDArray[Any]) -> None:
        """Add a detector layer to the viewer.

        Parameters
        ----------
        data : ``npt.NDArray[Any]``
            The image data to be added as a detector layer.
        """
        layer = self.viewer_model.add_image(
            data,
            name="My Detector",
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

        self._roi_controls[layer] = SettingsControlWidget(layer)
        self.viewer_window.add_dock_widget(
            self._roi_controls[layer],
            name=f"{layer.name}",
            area="right",
            tabify=True,
        )

    def registration_phase(self) -> None:
        self.virtual_bus.register_signals(self)

    def connection_phase(self) -> None:
        self.virtual_bus["DetectorController"]["sigDetectorConfigDescriptor"].connect(
            self._update_parameter_layout
        )
        self.virtual_bus["DetectorController"]["sigDetectorConfigReading"].connect(
            self._update_parameter
        )
        self.sigConfigRequest.emit()

    def _on_resize_request(
        self, layer: Image, dx: int, dy: int, width: int, height: int
    ) -> None:
        """Handle resize requests for the ROI box.

        Parameters
        ----------
        layer : Image
            The image layer to resize.
        dx : int
            The x-coordinate of the top-left corner of the ROI.
        dy : int
            The y-coordinate of the top-left corner of the ROI.
        width : int
            The width of the ROI.
        height : int
            The height of the ROI.
        """
        layer._overlays["roi_box"].bounds = ((dy, dx), (dy + height, dx + width))
        layer.events

    def _update_parameter_layout(
        self, detector: str, descriptor: dict[str, Descriptor]
    ) -> None:
        self.settings_tree_view.model().add_device(detector, descriptor)

    def _update_parameter(
        self, detector: str, reading: dict[str, Reading[Any]]
    ) -> None:
        self.settings_tree_view.model().update_readings(detector, reading)

    def _on_structure_changed(self) -> None:
        self.settings_tree_view.expandAll()
        for i in range(self.settings_tree_view.model().columnCount()):
            self.settings_tree_view.resizeColumnToContents(i)
