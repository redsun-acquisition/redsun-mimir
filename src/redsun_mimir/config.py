from sunflare.config import ControllerInfo, WidgetInfo

__all__ = ["StageControllerInfo"]


# Add your custom configuration variables here
class StageControllerInfo(ControllerInfo):
    """Configuration class for the stage controller."""

    # TODO: fill
    string: str
    integer: int
    boolean: bool


class StageWidgetInfo(WidgetInfo):
    """Configuration class for the stage widget."""

    # TODO: fill
    string: str
    integer: int
    boolean: bool
