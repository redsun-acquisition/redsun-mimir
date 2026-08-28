from napari._vispy.utils.visual import overlay_to_visual

from ._callbacks import highlight_roi_box_handles, resize_selection_box
from ._overlay import ROIInteractionBoxOverlay, VispyROIBoxOverlay
from ._theme import stylesheet

overlay_to_visual.update({ROIInteractionBoxOverlay: VispyROIBoxOverlay})

__all__ = [
    "ROIInteractionBoxOverlay",
    "highlight_roi_box_handles",
    "resize_selection_box",
    "stylesheet",
]
