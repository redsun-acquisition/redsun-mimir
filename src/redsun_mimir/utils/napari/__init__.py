from napari._qt.layer_controls.qt_layer_controls_container import layer_to_controls
from napari._vispy.utils.visual import overlay_to_visual

from ._controls import DetectorLayerControls
from ._layer import DetectorLayer
from ._overlay import ROIInteractionBoxOverlay, VispyROIBoxOverlay

overlay_to_visual.update({ROIInteractionBoxOverlay: VispyROIBoxOverlay})
layer_to_controls.update({DetectorLayer: DetectorLayerControls})

__all__ = [
    "DetectorLayer",
]
