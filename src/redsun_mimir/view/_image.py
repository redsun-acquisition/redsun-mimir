from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
from napari.components import ViewerModel
from napari.window import Window
from sunflare.log import Loggable
from sunflare.view.qt import QtView

from redsun_mimir.utils.napari import (
    ROIInteractionBoxOverlay,
    highlight_roi_box_handles,
    resize_selection_box,
)

if TYPE_CHECKING:
    import numpy.typing as npt
    from bluesky.protocols import Descriptor, Reading
    from sunflare.virtual import VirtualBus


class ImageView(QtView, Loggable):
    """View for live image display in a napari viewer.

    Manages a [`napari.components.ViewerModel`][] and its associated
    [`napari.window.Window`][]. One image layer is created per detector;
    layers are updated in real-time as new data arrives from the presenter.

    Parameters
    ----------
    virtual_bus :
        Reference to the virtual bus.
    **kwargs :
        Additional keyword arguments passed to the parent view.

    Note
    ----
    This class handles only *visualisation*. Property editing lives in
    [`DetectorView`][redsun_mimir.view.DetectorView].
    """

    def __init__(
        self,
        virtual_bus: VirtualBus,
        /,
        **kwargs: Any,
    ) -> None:
        super().__init__(virtual_bus, **kwargs)

        self.viewer_model = ViewerModel(
            title="Image viewer", ndisplay=2, order=(), axis_labels=()
        )

        # TODO: replace with a lightweight napari component instead of
        # the full Window (see Task 4).
        self.viewer_window = Window(
            viewer=self.viewer_model,
            show=False,
        )

        self.buffer_key = "buffer"

        self.logger.info("Initialized")

    def connect_to_virtual(self) -> None:
        """Connect to presenter signals on the virtual bus."""
        self.virtual_bus.signals["DetectorPresenter"]["sigNewData"].connect(
            self._update_layers, thread="main"
        )
        try:
            self.virtual_bus.signals["MedianPresenter"]["sigNewData"].connect(
                self._update_layers, thread="main"
            )
        except KeyError:
            self.logger.debug(
                "MedianPresenter not found in virtual bus; skipping median data connection."
            )

    def setup_layers(
        self,
        descriptors: dict[str, Descriptor],
        readings: dict[str, Reading[Any]],
        device_label: str,
        dev_descriptors: dict[str, Descriptor],
        dev_readings: dict[str, Reading[Any]],
    ) -> None:
        """Add a napari image layer for *device_label*.

        Called once per device during
        [`DetectorView.setup_ui`][redsun_mimir.view.DetectorView.setup_ui]
        so that both views share the same initialisation pass.

        Parameters
        ----------
        descriptors :
            Full merged descriptor dict (all devices).
        readings :
            Full merged readings dict (all devices).
        device_label :
            Human-readable device name, used as the layer name.
        dev_descriptors :
            Descriptor subset for this device only.
        dev_readings :
            Readings subset for this device only.
        """
        # Derive sensor shape from the first array descriptor for this device
        sensor_shape = (512, 512)
        for key, reading in dev_readings.items():
            if descriptors[key].get("dtype") == "array" and "sensor_shape" in key:
                val = reading["value"]
                if isinstance(val, (list, tuple)) and len(val) == 2:
                    sensor_shape = (int(val[0]), int(val[1]))
                break

        # Infer numpy dtype from buffer descriptor if available
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
        """Update image layers with incoming frame data.

        Parameters
        ----------
        data :
            Nested dict keyed by detector name.  Each value is a packet
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
