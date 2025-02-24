from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("redsun-mimir")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "unknown"

from .config import StageControllerInfo, StageModelInfo, StageWidgetInfo
from .controller import StageController
from .model import MockStageModel
from .widget import StageWidget

__all__ = (
    "StageController",
    "MockStageModel",
    "StageModelInfo",
    "StageWidget",
    "StageControllerInfo",
    "StageWidgetInfo",
)
