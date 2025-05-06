from __future__ import annotations

from typing import TYPE_CHECKING

from napari._qt.widgets.qt_mode_buttons import QtModePushButton
from napari.components import ViewerModel
from napari.window import Window
from qtpy import QtWidgets
from sunflare.view.qt import BaseQtWidget

if TYPE_CHECKING:
    from typing import Any

    import numpy.typing as npt
    from napari._qt.layer_controls.qt_image_controls import QtImageControls
    from napari.components.overlays import SelectionBoxOverlay
    from napari.layers import Image, Layer
    from napari.utils.events import EventedList
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
            config=config,
            virtual_bus=virtual_bus,
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

        delimit_indeces = self._model.layers._delitem_indices

        def _delimit_unprotected_indeces(
            key: int | slice,
        ) -> list[tuple[EventedList[Layer], int]]:
            """Populate the indices of the layers to be deleted.

            If a layer is protected, it will not be deleted.
            This is a workaround to prevent the deletion of protected layers.

            Parameters
            ----------
            key : ``int | slice``
                The key to be used for deletion.
            """
            indices: list[tuple[EventedList[Layer], int]] = delimit_indeces(key)
            for index in indices[:]:
                layer = index[0][index[1]]
                if getattr(layer, "protected", False):
                    indices.remove(index)
            return indices

        # monkey patch the _delitem_indices method to prevent deletion of protected layers
        self._model.layers._delitem_indices = _delimit_unprotected_indeces

    def add_image(self, data: npt.NDArray[Any], protected: bool = True) -> None:
        """Add an image to the viewer.

        Parameters
        ----------
        data : ``npt.NDArray[Any]``
            The image data to be added.
        protected : ``bool``, optional
            If ``True``, the layer will be protected from deletion.
        """
        layer: Image = self._model.add_image(data)
        setattr(layer, "protected", protected)

        if protected:
            roi: SelectionBoxOverlay = layer._overlays["selection_box"]
            roi.handles = True
            roi.bounds = (0, 0), (data.shape[1], data.shape[0])

            layer_ctrl: QtImageControls = self._layer_controls.widgets[layer]
            bbox_button = QtModePushButton(
                layer=layer,
                button_name="bbox_button",
                tooltip="Toggle the layer bounding box",
            )
            bbox_button.setCheckable(True)
            bbox_button.setChecked(False)
            bbox_button.toggled[bool].connect(
                lambda checked: self._toggle_bounding_box(layer, checked)
            )
            roi_button = QtModePushButton(
                layer=layer,
                button_name="roi_button",
                tooltip="Toggle the layer ROI box",
            )
            roi_button.setCheckable(True)
            roi_button.setChecked(False)
            roi_button.toggled[bool].connect(
                lambda checked: self._toggle_selection_overlay(layer, checked)
            )

            # add button before pan/zoom (0, 6) and transform (0, 7);
            layer_ctrl.button_grid.addWidget(bbox_button, 0, 5)
            layer_ctrl.button_grid.addWidget(roi_button, 0, 4)

    def registration_phase(self) -> None:
        self.virtual_bus.register_signals(self)

    def connection_phase(self) -> None: ...

    def _toggle_bounding_box(self, layer: Image, checked: bool) -> None:
        """Toggle the bounding box of the layer.

        Parameters
        ----------
        layer : ``Image``
            The image layer to toggle the bounding box for.
        checked : ``bool``
            If ``True``, the bounding box will be shown; otherwise, it will be hidden.

        """
        layer.bounding_box.visible = checked

    def _toggle_selection_overlay(self, layer: Image, checked: bool) -> None:
        """Toggle the selection overlay of the layer.

        Parameters
        ----------
        layer : ``Image``
            The image layer to toggle the selection overlay for.
        checked : ``bool``
            If ``True``, the selection overlay will be shown; otherwise, it will be hidden.

        """
        roi: SelectionBoxOverlay = layer._overlays["selection_box"]
        roi.visible = checked
