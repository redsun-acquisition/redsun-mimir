from ._acquisition import AcquisitionWidget
from ._config import (
    AcquisitionWidgetInfo,
    DetectorWidgetInfo,
    LightWidgetInfo,
    StageWidgetInfo,
)
from ._detector import DetectorWidget
from ._light import LightWidget
from ._stage import StageWidget

__all__ = [
    "AcquisitionWidget",
    "AcquisitionWidgetInfo",
    "StageWidget",
    "StageWidgetInfo",
    "LightWidget",
    "LightWidgetInfo",
    "DetectorWidget",
    "DetectorWidgetInfo",
]
