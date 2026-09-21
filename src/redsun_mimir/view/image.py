from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from napari._app_model import get_app_model
from napari._qt._qapp_model.injection._qproviders import register_qt_types
from napari._qt.qt_event_loop import get_qapp
from napari._qt.qt_viewer import QtViewer
from napari.components import ViewerModel
from napari.utils._proxies import PublicOnlyProxy
from qtpy import QtCore, QtGui, QtWidgets
from redsun.log import Loggable
from redsun.view import ViewPosition
from redsun.view.qt import QtView
from redsun.virtual import slot

from redsun_mimir.providers import DETECTOR_LAYER_SPECS

if TYPE_CHECKING:
    from typing import Any

    from bluesky.protocols import Reading
    from numpy.typing import NDArray
    from redsun.virtual import VirtualContainer

    from redsun_mimir.protocols import LayerSpec


def place(canvas: NDArray[Any], frame: NDArray[Any], origin: tuple[int, int]) -> bool:
    """Write *frame* into *canvas* with its top-left corner at *origin*, as ``(x, y)``.

    A frame the size of the canvas replaces it whole. Returns whether the
    frame fit; nothing is written when it does not.
    """
    x, y = origin
    height, width = frame.shape[:2]
    if (height, width) == canvas.shape[:2]:
        canvas[...] = frame
        return True
    if x < 0 or y < 0 or y + height > canvas.shape[0] or x + width > canvas.shape[1]:
        return False
    canvas[y : y + height, x : x + width] = frame
    return True


class ImageView(QtView, Loggable):
    """View for live image display in a napari viewer.

    Composes a [`napari.components.ViewerModel`][] with a
    [`napari._qt.qt_viewer.QtViewer`][] embedded directly as a child widget,
    bypassing napari's full ``Window``/``_QtMainWindow`` stack. The layer
    controls and layer list panels are extracted from ``QtViewer`` and placed
    in a dedicated left panel, giving full layout control without the napari
    menu bar, status bar, or other main-window chrome.

    One image layer is created per detector during
    [`inject_dependencies`][redsun_mimir.view.ImageView.inject_dependencies];
    layers are updated in real-time as new frames arrive from the presenter.

    The widget sets no stylesheet of its own; it is styled by the application
    it is built under, so a session that wants napari's theme puts napari's QSS
    on the application.

    Parameters
    ----------
    name :
        Identity key of the view.
    """

    @property
    def view_position(self) -> ViewPosition:
        """The position in the main view."""
        return ViewPosition.CENTER

    def __init__(
        self,
        name: str,
        /,
    ) -> None:
        super().__init__(name)

        # Ensure the QApplication exists and napari's theme search paths
        # (theme_<name>:/) are registered via QDir.addSearchPath.
        # Normally Window.__init__ triggers this via get_qapp(); since we
        # bypass Window entirely we call it explicitly here.
        get_qapp()

        self.viewer_model = ViewerModel(
            title="viewer-model", ndisplay=2, order=(), axis_labels=()
        )
        self.viewer_model.grid.enabled = True
        #: where a detector's frame lands on its layer, from its ROI
        self._origins: dict[str, tuple[int, int]] = {}

        register_qt_types()

        # QtViewer is a QSplitter containing the canvas and the dims bar.
        # It does not carry any main-window chrome (no menu bar, status bar,
        # activity dialog, etc.), making it safe to embed as a child widget.
        self._qt_viewer = QtViewer(self.viewer_model, show_welcome_screen=False)

        def _provide_embedded_viewer() -> ViewerModel | None:
            return PublicOnlyProxy(self.viewer_model)

        def _provide_embedded_qt_viewer() -> QtViewer | None:
            return self._qt_viewer

        self._provider_disposer = get_app_model().injection_store.register(
            providers=[(_provide_embedded_viewer,), (_provide_embedded_qt_viewer,)],
        )

        # Access the sub-panels via QtViewer's lazy properties so they are
        # initialised and correctly wired to the viewer model before we
        # reparent them into our own layout.
        controls = self._qt_viewer.controls
        layer_buttons = self._qt_viewer.layerButtons
        layer_list = self._qt_viewer.layers
        viewer_buttons = self._qt_viewer.viewerButtons

        # Left panel: layer controls on top, layer list + buttons below.
        left_panel = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout()
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        left_layout.addWidget(controls)
        left_layout.addWidget(layer_buttons)
        left_layout.addWidget(layer_list)
        left_layout.addWidget(viewer_buttons)
        left_panel.setLayout(left_layout)

        # Horizontal splitter: left panel | canvas+dims
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(self._qt_viewer)
        splitter.setStretchFactor(0, 0)  # left panel: fixed preferred size
        splitter.setStretchFactor(1, 1)  # canvas: takes all remaining space

        main_layout = QtWidgets.QHBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(splitter)
        self.setLayout(main_layout)
        self.seen_layers: set[str] = set()

        self.logger.info("Initialized")

    def closeEvent(self, event: QtGui.QCloseEvent | None) -> None:  # noqa: D102
        # Unregister the embedded viewer/qt-viewer providers on teardown
        self._provider_disposer.cleanup()
        super().closeEvent(event)

    def register_providers(self, container: VirtualContainer) -> None:
        """Register image view signals in the virtual container."""
        container.register_signals(self)

    def inject_dependencies(self, container: VirtualContainer) -> None:
        """Create one image layer per detector."""
        self.setup_layers(container.require(DETECTOR_LAYER_SPECS))

    def setup_layers(self, specs: dict[str, LayerSpec]) -> None:
        """Create an empty, sensor-sized image layer for each detector."""
        for name, spec in specs.items():
            self.logger.debug(f"Creating layer for {name} with spec {spec}")
            buffer = np.zeros(spec["shape"], dtype=np.dtype(spec["dtype"]))
            self.viewer_model.add_image(buffer, name=name)
            self._origins[name] = (0, 0)

    @slot
    def update_layers(self, data: dict[str, Reading[Any]]) -> None:
        """Push incoming frame data into the corresponding image layers.

        A detector's frame is drawn into the rectangle of its layer that its
        ROI names, the reading beside it says which; the layer keeps the
        sensor's size. Any other reading replaces its layer's data.

        Parameters
        ----------
        data : dict[str, Reading[Any]]
            Incoming reading from a detector buffer.
        """
        for key, reading in data.items():
            if key.endswith("-roi"):
                x, y = (int(item) for item in reading["value"][:2])
                self._origins[key.removesuffix("-roi")] = (x, y)
                continue
            name = key.removesuffix("-buffer")
            img = reading["value"]
            if name not in self.viewer_model.layers:
                self.logger.debug(f"Adding new layer for {name}")
                self.viewer_model.add_image(img, name=name)
                continue
            layer = self.viewer_model.layers[name]
            origin = self._origins.get(name)
            if origin is not None and place(layer.data, img, origin):
                layer.refresh()
            else:
                layer.data = img
