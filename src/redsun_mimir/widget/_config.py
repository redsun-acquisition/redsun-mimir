from __future__ import annotations

from attrs import define
from sunflare.config import WidgetInfo


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
