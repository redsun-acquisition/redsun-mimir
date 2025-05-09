from __future__ import annotations

from napari.layers.base._base_constants import StringEnum


class ExtendedMode(StringEnum):  # type: ignore[misc]
    """Interactive mode enumerator. Extended from the original `napari.layers.base._base_constants.Mode`.

    - PAN_ZOOM: default mode (interactivity with the canvas);
    - TRANSFORM: transform mode (interactivity with the layer transformation);
    - RESIZE: resize mode (interactivity with the layer layer overlay ROI box);
    """

    PAN_ZOOM = "pan_zoom"
    TRANSFORM = "transform"
    RESIZE = "resize"
