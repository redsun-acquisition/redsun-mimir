from __future__ import annotations

from typing import TYPE_CHECKING

from napari.components import ViewerModel
from napari.window import Window
from qtpy import QtWidgets
from sunflare.view.qt import BaseQtWidget

from redsun_mimir.utils.napari import DetectorLayer

if TYPE_CHECKING:
    from typing import Any

    import numpy.typing as npt
    from napari.layers import Layer
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

        delimit_indeces = self._model.layers._delitem_indices

        def _delimit_unprotected_indeces(
            key: int | slice,
        ) -> list[tuple[EventedList[Layer], int]]:
            """Populate the indices of the layers to be deleted.

            This method is a monkey patch for the ``_delitem_indices`` method of the
            ``napari.components._model.Layers`` class. It prevents the deletion of
            detector layers by removing them from the list of indices to be deleted.

            Parameters
            ----------
            key : ``int | slice``
                The key to be used for deletion.
            """
            indices: list[tuple[EventedList[Layer], int]] = delimit_indeces(key)
            for index in indices[:]:
                layer = index[0][index[1]]
                if isinstance(layer, DetectorLayer):
                    # if the layer is a detector layer, do not delete it
                    indices.remove(index)
            return indices

        # monkey patch the _delitem_indices method to prevent deletion of protected layers
        self._model.layers._delitem_indices = _delimit_unprotected_indeces

    def add_detector(self, data: npt.NDArray[Any]) -> None:
        """Add a detector layer to the viewer.

        Parameters
        ----------
        data : ``npt.NDArray[Any]``
            The image data to be added as a detector layer.
        """
        layer = DetectorLayer(data)
        self._model.layers.append(layer)

    def registration_phase(self) -> None:
        self.virtual_bus.register_signals(self)

    def connection_phase(self) -> None: ...
