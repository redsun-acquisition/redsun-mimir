from __future__ import annotations

from functools import partial
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
from redsun.virtual import Signal, slot

from redsun_mimir.providers import DETECTOR_LAYER_SPECS
from redsun_mimir.roi import Roi
from redsun_mimir.utils.napari import (
    ROIInteractionBoxOverlay,
    highlight_roi_box_handles,
    resize_selection_box,
)

if TYPE_CHECKING:
    from typing import Any

    from bluesky.protocols import Reading
    from numpy.typing import NDArray
    from redsun.virtual import VirtualContainer

    from redsun_mimir.protocols import LayerSpec

#: The key a detector layer's selection box is kept under, which the mouse
#: callbacks in ``utils.napari`` look it up by.
ROI_BOX = "roi_box"


def roi_from_bounds(
    bounds: tuple[tuple[float, float], tuple[float, float]], sensor: tuple[int, int]
) -> Roi:
    """Turn a selection box, two corners in layer pixels, into a ROI on the sensor.

    Corners are ``(y, x)``, as napari keeps them; *sensor* is ``(height,
    width)``. The rectangle is rounded to whole pixels, clamped to the sensor
    and at least one pixel wide and high.
    """
    height, width = sensor
    (y0, x0), (y1, x1) = bounds
    left = min(max(round(min(x0, x1)), 0), width - 1)
    top = min(max(round(min(y0, y1)), 0), height - 1)
    right = min(max(round(max(x0, x1)), left + 1), width)
    bottom = min(max(round(max(y0, y1)), top + 1), height)
    return Roi(left, top, right - left, bottom - top)


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

    Each detector layer carries a selection box the user drags by its handles
    to choose a region of the sensor. Dragging changes nothing on the camera:
    the box is announced on ``sig_roi_drawn`` and applied by whoever confirms
    it; once applied, the box follows the region the camera reads.

    Parameters
    ----------
    name :
        Identity key of the view.

    Attributes
    ----------
    sig_roi_drawn : Signal[str, Roi]
        Emitted as the selection box on a detector's layer is dragged, with
        the detector's name and the box as a `Roi` in sensor pixels. The box
        is hidden, and cannot be dragged, until `set_roi_selection` shows it.
    """

    sig_roi_drawn = Signal(str, object)

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
        #: each detector layer's size, (height, width), which a box is clamped to
        self._sensors: dict[str, tuple[int, int]] = {}

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
        """Create an empty, sensor-sized image layer for each detector, with its box.

        The box starts over the whole sensor, which is what an uncropped
        camera reads out, and hidden until a selection is asked for.
        """
        for name, spec in specs.items():
            self.logger.debug(f"Creating layer for {name} with spec {spec}")
            buffer = np.zeros(spec["shape"], dtype=np.dtype(spec["dtype"]))
            layer = self.viewer_model.add_image(buffer, name=name)
            self._origins[name] = (0, 0)
            self._sensors[name] = spec["shape"]
            box = ROIInteractionBoxOverlay(
                bounds=((0, 0), spec["shape"]), handles=True, visible=False
            )
            layer._overlays[ROI_BOX] = box
            layer.mouse_drag_callbacks.append(resize_selection_box)
            layer.mouse_move_callbacks.append(highlight_roi_box_handles)
            box.events.bounds.connect(partial(self._on_box_drawn, name))

    def _on_box_drawn(self, detector: str, event: object = None) -> None:
        """Announce where the box on *detector*'s layer now stands."""
        box = self.viewer_model.layers[detector]._overlays[ROI_BOX]
        self.sig_roi_drawn.emit(
            detector, roi_from_bounds(box.bounds, self._sensors[detector])
        )

    @slot
    def set_roi_selection(self, detector: str, enabled: bool) -> None:
        """Show the box on *detector*'s layer and let it be dragged, or hide it."""
        if detector in self.viewer_model.layers:
            self.viewer_model.layers[detector]._overlays[ROI_BOX].visible = enabled

    @slot
    def on_new_configuration(self, detector: str, key: str, value: object) -> None:
        """Put the box over the region the camera reads, once a ROI is applied.

        *key* is the setting's data key, ``<detector>-roi`` for the one this
        view shows; any other setting is not this view's to show.
        """
        if key != f"{detector}-roi" or detector not in self.viewer_model.layers:
            return
        roi = Roi.parse(str(value))
        box = self.viewer_model.layers[detector]._overlays[ROI_BOX]
        with box.events.bounds.blocked():
            box.bounds = ((roi.y, roi.x), (roi.y + roi.height, roi.x + roi.width))

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
                roi: Roi = reading["value"]
                self._origins[key.removesuffix("-roi")] = (roi.x, roi.y)
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
