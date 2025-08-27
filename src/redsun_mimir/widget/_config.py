from __future__ import annotations

from attrs import define, field, setters
from sunflare.config import ViewInfo


@define
class MotorWidgetInfo(ViewInfo):
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
class DetectorWidgetInfo(ViewInfo):
    """Detector widget information.

    Parameters
    ----------
    viewer_title : str
        Title of the viewer.
        Defaults to "Image viewer".
    """

    viewer_title: str = field(
        default="Image viewer",
        on_setattr=setters.frozen,
    )
