from __future__ import annotations

from typing import TYPE_CHECKING

from napari import Viewer
from napari._qt.widgets.qt_mode_buttons import QtModePushButton
from qtpy import QtWidgets
from sunflare.view.qt import BaseQtWidget

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
            config=config,
            virtual_bus=virtual_bus,
            *args,
            **kwargs,
        )

        self.viewer = Viewer(
            title="Image viewer",
            ndisplay=2,
            order=(),
            axis_labels=(),
            show=False,
        )

        # disable the default menu bar
        # menus = self.viewer.window._qt_window.findChildren(QtWidgets.QMenuBar)
        # for menu in menus:
        #     menu.setEnabled(False)
        #     menu.setVisible(False)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.viewer.window._qt_window)
        self.setLayout(layout)

    def add_image(self, data: npt.NDArray[Any], is_detector: bool) -> None:
        """Add an image to the viewer.

        Parameters
        ----------
        data : ``npt.NDArray[Any]``
            The image data to be added.
        is_detector : ``bool``, optional
            If ``True``, the image is considered a detector-dedicated layer;
            it will be protected from deletion and custom buttons will be added.

        """
        ret: Image = self.viewer.add_image(data)
        setattr(ret, "protected", is_detector)

        if is_detector:
            controls: QtImageControls = self.viewer.window.qt_viewer.controls.widgets[
                ret
            ]
            controls.button_grid
            QtModePushButton(
                layer=ret,
                button_name="bounding_box_button",
            )

    def registration_phase(self) -> None:
        self.virtual_bus.register_signals(self)

    def connection_phase(self) -> None: ...
