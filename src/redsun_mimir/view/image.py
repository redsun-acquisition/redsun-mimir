from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from napari._app_model import get_app_model
from napari._qt.qt_event_loop import get_qapp
from napari._qt.qt_resources import get_stylesheet
from napari._qt.qt_viewer import QtViewer
from napari.components import ViewerModel
from napari.settings import get_settings
from napari.utils._proxies import PublicOnlyProxy
from napari.viewer import (
    Viewer,  # noqa: TC002 (needed for napari injection until 0.7.0)
)
from qtpy import QtCore, QtGui, QtWidgets
from redsun.log import Loggable
from redsun.view import ViewPosition
from redsun.view.qt import QtView

if TYPE_CHECKING:
    from typing import Any

    from bluesky.protocols import Reading
    from redsun.virtual import VirtualContainer

    from redsun_mimir.protocols import LayerSpec


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

        # QtViewer is a QSplitter containing the canvas and the dims bar.
        # It does not carry any main-window chrome (no menu bar, status bar,
        # activity dialog, etc.), making it safe to embed as a child widget.
        self._qt_viewer = QtViewer(self.viewer_model, show_welcome_screen=False)

        # TODO: this is an hotfix to make the application not crash
        # when manually deleting layers from the viewer; it should
        # go away once napari 0.7.0 is released, which allows
        # to manipulate the viewer model more easily
        def _provide_embedded_viewer() -> Viewer | None:
            return PublicOnlyProxy(self.viewer_model)

        self._provider_disposer = get_app_model().injection_store.register(
            providers=[(_provide_embedded_viewer,)]
        )

        # Access the sub-panels via QtViewer's lazy properties so they are
        # initialised and correctly wired to the viewer model before we
        # reparent them into our own layout.
        controls = self._qt_viewer.controls
        layer_buttons = self._qt_viewer.layerButtons
        layer_list = self._qt_viewer.layers

        # Left panel: layer controls on top, layer list + buttons below.
        left_panel = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout()
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        left_layout.addWidget(controls)
        left_layout.addWidget(layer_buttons)
        left_layout.addWidget(layer_list)
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

        # Apply napari's stylesheet so icons and theme colours render correctly.
        # Window.__init__ normally does this via _update_theme(); since we bypass
        # Window entirely we do it here and re-apply on theme changes.
        self._apply_napari_stylesheet()

        self.logger.info("Initialized")

    def closeEvent(self, event: QtGui.QCloseEvent | None) -> None:  # noqa: D102
        # on teardown, ensure we unregister the
        # embedded viewer provider to keep things clean;
        # TODO: this should go away after napari 0.7.0 is released
        self._provider_disposer()
        super().closeEvent(event)

    def _apply_napari_stylesheet(self) -> None:
        """Apply (or re-apply) napari's QSS theme to this widget and the canvas.

        Normally ``Window._update_theme`` does this; since we bypass ``Window``
        entirely we call it once at startup and reconnect it to the theme-change
        event so that live theme switching keeps working.
        """
        settings = get_settings()
        theme = settings.appearance.theme
        font_size = f"{settings.appearance.font_size}pt"
        stylesheet: str = get_stylesheet(
            theme, extra_variables={"font_size": font_size}
        )
        self.setStyleSheet(stylesheet)
        self._qt_viewer.setStyleSheet(stylesheet)

    def register_providers(self, container: VirtualContainer) -> None:
        """Register image view signals in the virtual container."""
        container.register_signals(self)

    def inject_dependencies(self, container: VirtualContainer) -> None:
        """Inject detector configuration and create image layers."""
        specs: dict[str, LayerSpec] = container.detector_layer_specs()
        self.setup_layers(specs)
        for cache in container.signals.values():
            if "sigNewData" in cache:
                cache["sigNewData"].connect(self._update_layers, thread="main")
            if "sigNewMedian" in cache:
                cache["sigNewMedian"].connect(self._update_layers, thread="main")

    def setup_layers(self, specs: dict[str, LayerSpec]) -> None:
        """Create an empty image layer for each detector based on the provided specifications."""
        for name, spec in specs.items():
            self.logger.debug(f"Creating layer for {name} with spec {spec}")
            buffer = np.zeros(spec["shape"], dtype=np.dtype(spec["dtype"]))
            self.viewer_model.add_image(buffer, name=name)

    def _update_layers(self, data: dict[str, Reading[Any]]) -> None:
        """Push incoming frame data into the corresponding image layers.

        Parameters
        ----------
        data : dict[str, Reading[Any]]
            Incoming reading from a detector buffer.
        """
        for name, reading in data.items():
            name = name.removesuffix("-buffer")
            if name not in self.viewer_model.layers:
                self.logger.debug(f"Adding new layer for {name}")
                self.viewer_model.add_image(reading["value"], name=name)
            else:
                self.viewer_model.layers[name].data = reading["value"]
