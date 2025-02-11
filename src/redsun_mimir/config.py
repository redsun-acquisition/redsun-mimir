from __future__ import annotations

from attrs import define, field, validators
from sunflare.config import ControllerInfo, ModelInfo, WidgetInfo

__all__ = ["StageControllerInfo", "StageWidgetInfo"]


class StageModelInfo(ModelInfo):
    """Configuration class for the stage model.

    Parameters
    ----------
    egu : str, optional
        Engineering units. Default is "mm".
    axis : list[str]
        Axis names. Reccomended to be capital single characters.
        (i.e. ["X", "Y", "Z"])
    step_sizes : dict[str, float]
        Step sizes for each axis.
        (i.e. {"X": 0.1, "Y": 0.1, "Z": 0.1})

    """

    egu: str = field(
        default="mm",
        validator=validators.instance_of(str),
        metadata={"description": "Engineering units."},
    )
    axis: list[str] = field(
        validator=validators.instance_of(list),
        metadata={"description": "Axis names."},
    )
    step_sizes: dict[str, float] = field(
        validator=validators.instance_of(dict),
        metadata={"description": "Step sizes for each axis."},
    )


@define
class StageControllerInfo(ControllerInfo):
    """Configuration class for the stage controller."""

    ...


@define
class StageWidgetInfo(WidgetInfo):
    """Configuration class for the stage widget."""

    ...
