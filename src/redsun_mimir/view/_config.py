from __future__ import annotations

from attrs import define, field, setters


@define
class MotorWidgetInfo:
    """Stage widget information.

    Currently provides no additional information.
    """

    ...


@define
class LightWidgetInfo:
    """Light widget information.

    Currently provides no additional information.
    """

    ...


@define
class AcquisitionWidgetInfo:
    """Acquisition widget information.

    Currently provides no additional information.
    """

    ...


@define
class DetectorWidgetInfo:
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
