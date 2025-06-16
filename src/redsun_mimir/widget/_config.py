from __future__ import annotations

from attrs import define, field, setters
from sunflare.config import WidgetInfo, WidgetPositionTypes


@define
class StageWidgetInfo(WidgetInfo):
    """Stage widget information.

    Currently provides no additional information.
    """

    ...


@define
class LightWidgetInfo(WidgetInfo):
    """Light widget information.

    Currently provides no additional information.
    """

    ...


@define
class AcquisitionWidgetInfo(WidgetInfo):
    """Acquisition widget information.

    Currently provides no additional information.
    """

    ...


@define
class ImageWidgetInfo(WidgetInfo):
    """Image widget information.

    Overrides the default position to ensure it is
    always put as the center widget in the main window.
    """

    position: WidgetPositionTypes = field(
        default=WidgetPositionTypes.CENTER,
        on_setattr=setters.frozen,
    )
