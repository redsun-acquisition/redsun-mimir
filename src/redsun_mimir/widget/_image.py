from __future__ import annotations

from typing import TYPE_CHECKING

from napari.components import ViewerModel
from napari.window import Window
from qtpy import QtWidgets
from sunflare.view.qt import BaseQtWidget
from sunflare.virtual import Signal

from redsun_mimir.utils.napari import (
    ROIInteractionBoxOverlay,
    highlight_roi_box_handles,
    resize_selection_box,
)

if TYPE_CHECKING:
    from typing import Any

    import numpy.typing as npt
    from napari.layers import Image
    from sunflare.config import RedSunSessionInfo
    from sunflare.virtual import VirtualBus


class ROIControlWidget(QtWidgets.QWidget):
    """Widget for controlling the ROI interaction box in the image viewer.

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

    sigFullROIRequest = Signal()
    sigNewROIRequest = Signal(int, int, int, int)  # dx, dy, width, height

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

        # forward the signals to the parent widget
        self._full_roi_button.clicked.connect(self.sigFullROIRequest)

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

    sigNewROIRequest = Signal(
        object, int, int, int, int
    )  # layer, dx, dy, width, height

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

        self._model = ViewerModel(
            title="Image viewer", ndisplay=2, order=(), axis_labels=()
        )
        self._window = Window(
            viewer=self._model,
            show=False,
        )

        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._window._qt_window)
        self.setLayout(layout)

        # keep a reference to the subcomponents of the viewer
        # for later use and easier access
        self._layer_list = self._window._qt_viewer.layers
        self._layer_controls = self._window._qt_viewer.controls

        self._roi_controls: dict[Image, ROIControlWidget] = {}

    def add_detector(self, data: npt.NDArray[Any]) -> None:
        """Add a detector layer to the viewer.

        Parameters
        ----------
        data : ``npt.NDArray[Any]``
            The image data to be added as a detector layer.
        """
        layer = self._model.add_image(
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

        self._roi_controls[layer] = ROIControlWidget(layer)
        self._window.add_dock_widget(
            self._roi_controls[layer],
            name=f"{layer.name}",
            area="right",
            tabify=True,
        )

        self._roi_controls[layer].sigFullROIRequest.connect(
            lambda: self.sigNewROIRequest.emit(
                layer, 0, 0, layer.data.shape[0], layer.data.shape[1]
            )
        )
        self._roi_controls[layer].sigNewROIRequest.connect(
            lambda dx, dy, width, height: self.sigNewROIRequest.emit(
                layer, dx, dy, width, height
            )
        )

    def registration_phase(self) -> None:
        self.virtual_bus.register_signals(self)

    def connection_phase(self) -> None: ...

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
