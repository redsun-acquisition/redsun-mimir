from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("redsun-mimir")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "unknown"


from .controller import StageController
from .config import StageControllerInfo
from .widget import StageWidget

__all__ = (
    "StageController",
    "StageControllerInfo",
)
