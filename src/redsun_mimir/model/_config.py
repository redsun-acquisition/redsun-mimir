from typing import Any

from attrs import define, field, setters, validators
from sunflare.config import ModelInfo


@define(kw_only=True)
class StageModelInfo(ModelInfo):
    """Configuration of a stage model.

    Parameters
    ----------
    egu : ``str``, optional
        Engineering units. Default is "mm".
    axis : ``list[str]``
        Axis names. Reccomended to be capital single characters.
        (i.e. ["X", "Y", "Z"])
    step_sizes : ``dict[str, float]``
        Step sizes for each axis.
        (i.e. {"X": 0.1, "Y": 0.1, "Z": 0.1})

    """

    egu: str = field(
        default="mm",
        validator=validators.instance_of(str),
        on_setattr=setters.frozen,
        metadata={"description": "Engineering units."},
    )
    axis: list[str] = field(
        validator=validators.instance_of(list),
        on_setattr=setters.frozen,
        metadata={"description": "Axis names."},
    )
    step_sizes: dict[str, float] = field(
        validator=validators.instance_of(dict),
        metadata={"description": "Step sizes for each axis."},
    )


def to_float_tuple(value: Any) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"Expected a list or tuple of length 2, got {value}")
    return tuple(float(v) for v in value)


@define(kw_only=True)
class LightModelInfo(ModelInfo):
    """Configuration of a light model.

    Parameters
    ----------
    wavelength : ``float``
        Wavelength in nm.
    egu : ``str``, optional
        Engineering units. Default is "mW".
    initial_intensity : ``float``, optional
        Initial light intensity. Default is 0.0.
    intensity_range : ``tuple[float, float]``
        Intensity range (min, max).
    step_size : ``int``, optional
        Step size for the intensity. Default is 1.

    """

    wavelength: float = field(
        converter=float,
        validator=validators.instance_of(float),
        metadata={"description": "Wavelength in nm."},
    )
    egu: str = field(
        default="mW",
        validator=validators.instance_of(str),
        on_setattr=setters.frozen,
        metadata={"description": "Engineering units."},
    )
    initial_intensity: float = field(
        default=0.0,
        validator=validators.instance_of(float),
        metadata={"description": "Initial light intensity."},
    )
    intensity_range: tuple[float, float] = field(
        converter=to_float_tuple,
        validator=validators.instance_of(tuple),
        metadata={"description": "Intensity range (min, max)."},
    )
    step_size: int = field(
        default=1,
        validator=validators.instance_of(int),
        metadata={"description": "Step size for the intensity."},
    )
