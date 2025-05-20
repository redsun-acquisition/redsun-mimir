from __future__ import annotations

from typing import TYPE_CHECKING

from napari._qt.widgets.qt_mode_buttons import QtModePushButton
from napari.components import ViewerModel
from napari.window import Window
from qtpy import QtWidgets
from sunflare.view.qt import BaseQtWidget

from redsun_mimir.utils.napari import (
    ROIInteractionBoxOverlay,
    highlight_roi_box_handles,
    resize_roi_box,
)

if TYPE_CHECKING:
    from typing import Any

    import numpy.typing as npt
    from napari._qt.layer_controls.qt_image_controls import QtImageControls
    from napari.layers import Image
    from sunflare.config import RedSunSessionInfo
    from sunflare.virtual import VirtualBus


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
            {"roi_box": ROIInteractionBoxOverlay(bounds=((0, 0), layer.data.shape))}
        )
        layer.mouse_drag_callbacks.append(resize_roi_box)
        layer.mouse_move_callbacks.append(highlight_roi_box_handles)
        controls: QtImageControls = self._layer_controls.widgets[layer]

        resize_button = QtModePushButton(
            layer=layer,
            button_name="resize",
            tooltip="Set the current portion of layer to visualize",
        )
        resize_button.setCheckable(True)
        resize_button.setChecked(False)
        resize_button.toggled[bool].connect(
            lambda checked: self._on_resize_button_toggled(layer, checked)
        )
        # add the new button to the layer controls, before the
        # mode buttons
        controls.button_grid.addWidget(resize_button, 0, 5)

    def registration_phase(self) -> None:
        self.virtual_bus.register_signals(self)

    def connection_phase(self) -> None: ...

    def _on_resize_button_toggled(self, layer: Image, checked: bool) -> None:
        layer.bounding_box.visible = checked
        layer._overlays["roi_box"].visible = checked
