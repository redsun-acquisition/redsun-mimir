from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
from napari._qt.containers.qt_layer_list import QtLayerList
from napari._qt.layer_controls import QtLayerControlsContainer
from napari._qt.qt_resources import get_stylesheet
from napari._qt.qt_viewer import QtViewer
from napari._qt.widgets.qt_viewer_buttons import QtLayerButtons, QtViewerButtons
from napari.components import ViewerModel
from napari.settings import get_settings
from qtpy import QtCore, QtWidgets
from sunflare.log import Loggable
from sunflare.view import ViewPosition
from sunflare.view.qt import QtView

from redsun_mimir.utils import find_signals
from redsun_mimir.utils.descriptors import parse_key
from redsun_mimir.utils.napari import (
    ROIInteractionBoxOverlay,
    highlight_roi_box_handles,
    resize_selection_box,
)

if TYPE_CHECKING:
    import numpy.typing as npt
    from bluesky.protocols import Descriptor, Reading
    from sunflare.virtual import VirtualContainer


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

    Property editing lives in the companion
    [`DetectorView`][redsun_mimir.view.DetectorView], which is wired
    independently through the virtual bus.

    Parameters
    ----------
    name :
        Identity key of the view.
    hints :
        Data key suffixes to watch for in incoming data packets.
        Currently unused; reserved for future filtering.
    """

    @property
    def view_position(self) -> ViewPosition:
        return ViewPosition.CENTER

    def __init__(
        self,
        name: str,
        /,
        hints: list[str] | None = None,
    ) -> None:
        super().__init__(name)

        self.viewer_model: ViewerModel = ViewerModel(
            title="Image viewer", ndisplay=2, order=(), axis_labels=()
        )

        # QtViewer is a QSplitter containing the canvas and the dims bar.
        # It does not carry any main-window chrome (no menu bar, status bar,
        # activity dialog, etc.), making it safe to embed as a child widget.
        self._qt_viewer: QtViewer = QtViewer(
            self.viewer_model, show_welcome_screen=False
        )

        # Access the sub-panels via QtViewer's lazy properties so they are
        # initialised and correctly wired to the viewer model before we
        # reparent them into our own layout.
        controls: QtLayerControlsContainer = self._qt_viewer.controls
        layer_buttons: QtLayerButtons = self._qt_viewer.layerButtons
        layer_list: QtLayerList = self._qt_viewer.layers
        viewer_buttons: QtViewerButtons = self._qt_viewer.viewerButtons

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

        self.buffer_key: str = "buffer"

        # Apply napari's stylesheet so icons and theme colours render correctly.
        # Window.__init__ normally does this via _update_theme(); since we bypass
        # Window entirely we do it here and re-apply on theme changes.
        self._apply_napari_stylesheet()
        get_settings().appearance.events.theme.connect(
            lambda _: self._apply_napari_stylesheet()
        )

        self.logger.info("Initialized")

    def _apply_napari_stylesheet(self) -> None:
        """Apply (or re-apply) napari's QSS theme to this widget and the canvas.

        Normally ``Window._update_theme`` does this; since we bypass ``Window``
        entirely we call it once at startup and reconnect it to the theme-change
        event so that live theme switching keeps working.
        """
        settings = get_settings()
        theme = settings.appearance.theme
        font_size = f"{settings.appearance.font_size}pt"
        stylesheet: str = get_stylesheet(theme, extra_variables={"font_size": font_size})
        self.setStyleSheet(stylesheet)
        self._qt_viewer.setStyleSheet(stylesheet)

    def register_providers(self, container: VirtualContainer) -> None:
        """Register image view signals in the virtual container."""
        container.register_signals(self)

    def inject_dependencies(self, container: VirtualContainer) -> None:
        """Inject detector configuration and create image layers."""
        descriptors: dict[str, Descriptor] = container.detector_descriptors()
        readings: dict[str, Reading[Any]] = container.detector_readings()
        self._setup_layers(descriptors, readings)
        sigs = find_signals(container, ["sigNewData"])
        if "sigNewData" in sigs:
            sigs["sigNewData"].connect(self._update_layers, thread="main")

    def _setup_layers(
        self,
        descriptors: dict[str, Descriptor],
        readings: dict[str, Reading[Any]],
    ) -> None:
        r"""Create one napari image layer per device.

        Parameters
        ----------
        descriptors :
            Flat merged ``describe_configuration()`` output from all detectors,
            keyed as ``prefix:name-property``.
        readings :
            Flat merged ``read_configuration()`` output, keyed identically.
        """
        devices: dict[str, dict[str, Descriptor]] = {}
        for key, descriptor in descriptors.items():
            try:
                name, _ = parse_key(key)
            except ValueError:
                self.logger.warning(f"Skipping malformed descriptor key: {key!r}")
                continue
            devices.setdefault(name, {})[key] = descriptor

        for device_label, dev_descriptors in devices.items():
            dev_readings: dict[str, Reading[Any]] = {
                k: v for k, v in readings.items() if k in dev_descriptors
            }

            sensor_shape: tuple[int, int] = (512, 512)
            for key, reading in dev_readings.items():
                if descriptors[key].get("dtype") == "array" and "sensor_shape" in key:
                    val = reading["value"]
                    if isinstance(val, (list, tuple)) and len(val) == 2:
                        sensor_shape = (int(val[0]), int(val[1]))
                    break

            dtype: str = "uint8"
            for key, desc in dev_descriptors.items():
                if desc.get("dtype") == "array" and "buffer" in key:
                    dtype = str(desc.get("dtype_numpy", "uint8"))
                    break

            layer = self.viewer_model.add_image(
                np.zeros(shape=sensor_shape, dtype=dtype),
                name=device_label,
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

    def _update_layers(self, data: dict[str, dict[str, Any]]) -> None:
        """Push incoming frame data into the corresponding image layers.

        Parameters
        ----------
        data :
            Nested dict keyed by detector name. Each value is a packet
            containing at least ``"buffer"`` (the raw frame array) and
            ``"roi"`` (a 4-tuple ``(x_start, x_end, y_start, y_end)``).
        """
        for obj_name, packet in data.items():
            buffer: npt.NDArray[Any] = packet[self.buffer_key]
            if obj_name not in self.viewer_model.layers:
                self.logger.debug(f"Adding new layer for {obj_name}")
                self.viewer_model.add_image(name=obj_name, data=buffer)
            else:
                self.viewer_model.layers[obj_name].data = buffer
