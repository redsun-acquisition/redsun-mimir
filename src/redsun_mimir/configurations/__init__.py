from ._acquisition_only import acquisition_widget
from ._detector_only import detector_widget
from ._detector_only_uc2 import detector_widget_uc2
from ._light_only import light_widget
from ._light_only_uc2 import light_widget_uc2
from ._motor_only import stage_widget
from ._motor_only_uc2 import stage_widget_uc2

__all__ = [
    "acquisition_widget",
    "stage_widget",
    "light_widget",
    "detector_widget",
    "detector_widget_uc2",
    "light_widget_uc2",
    "stage_widget_uc2",
]
