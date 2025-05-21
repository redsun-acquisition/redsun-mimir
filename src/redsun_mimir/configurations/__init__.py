from ._acquisition_only import acquisition_widget
from ._detector_only import detector_widget
from ._image_only import image_widget
from ._light_only import light_widget
from ._light_only_uc2 import light_widget_uc2
from ._stage_only import stage_widget

__all__ = [
    "acquisition_widget",
    "stage_widget",
    "light_widget",
    "detector_widget",
    "image_widget",
    "light_widget_uc2",
]
