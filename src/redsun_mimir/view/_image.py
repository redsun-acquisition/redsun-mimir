from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
from napari.components import ViewerModel
from napari.window import Window
from qtpy import QtWidgets
from sunflare.log import Loggable
from sunflare.view import ViewPosition
from sunflare.view.qt import QtView

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

    Manages a [`napari.components.ViewerModel`][] and its associated
    [`napari.window.Window`][]. One image layer is created per detector
    during [`inject_dependencies`][redsun_mimir.view.ImageView.inject_dependencies];
    layers are updated in real-time as new frames arrive from the presenter.

    Property editing lives in the companion
    [`DetectorView`][redsun_mimir.view.DetectorView], which is wired
    independently through the virtual bus.

    Parameters
    ----------
    virtual_bus :
        Reference to the virtual bus.
    **kwargs :
        Additional keyword arguments passed to the parent view.
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

        self.viewer_model = ViewerModel(
            title="Image viewer", ndisplay=2, order=(), axis_labels=()
        )

        # TODO: use napari components
        # instead of the full Window
        self.viewer_window = Window(
            viewer=self.viewer_model,
            show=False,
        )

        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.viewer_window._qt_window)
        self.setLayout(layout)

        self.buffer_key = "buffer"

        self.logger.info("Initialized")

    def register_providers(self, container: VirtualContainer) -> None:
        """Register image view signals in the virtual container."""
        container.register_signals(self)

    def inject_dependencies(self, container: VirtualContainer) -> None:
        """Inject detector configuration and create image layers."""
        descriptors: dict[str, Descriptor] = container.detector_descriptors()
        readings: dict[str, Reading[Any]] = container.detector_readings()
        self._setup_layers(descriptors, readings)

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
            dev_readings = {k: v for k, v in readings.items() if k in dev_descriptors}

            sensor_shape = (512, 512)
            for key, reading in dev_readings.items():
                if descriptors[key].get("dtype") == "array" and "sensor_shape" in key:
                    val = reading["value"]
                    if isinstance(val, (list, tuple)) and len(val) == 2:
                        sensor_shape = (int(val[0]), int(val[1]))
                    break

            dtype = "uint8"
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
