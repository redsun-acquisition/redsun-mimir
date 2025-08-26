from ._acquisition import acquisition_widget
from ._acquisition_uc2 import acquisition_widget_uc2
from ._detector import detector_widget
from ._detector_uc2 import detector_widget_uc2
from ._light import light_widget
from ._light_uc2 import light_widget_uc2
from ._motor import stage_widget
from ._motor_uc2 import stage_widget_uc2

__all__ = [
    "acquisition_widget",
    "acquisition_widget_uc2",
    "stage_widget",
    "light_widget",
    "detector_widget",
    "detector_widget_uc2",
    "light_widget_uc2",
    "stage_widget_uc2",
]
