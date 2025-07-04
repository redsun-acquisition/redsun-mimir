from __future__ import annotations

from attrs import define, field, setters
from sunflare.config import ViewInfo, WidgetPositionTypes


@define
class StageWidgetInfo(ViewInfo):
    """Stage widget information.

    Currently provides no additional information.
    """

    ...


@define
class LightWidgetInfo(ViewInfo):
    """Light widget information.

    Currently provides no additional information.
    """

    ...


@define
class AcquisitionWidgetInfo(ViewInfo):
    """Acquisition widget information.

    Currently provides no additional information.
    """

    ...


@define
class ImageWidgetInfo(ViewInfo):
    """Image widget information.

    Overrides the default position to ensure it is
    always put as the center widget in the main window.
    """

    position: WidgetPositionTypes = field(
        default=WidgetPositionTypes.CENTER,
        on_setattr=setters.frozen,
    )
