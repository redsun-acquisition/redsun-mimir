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
    wavelength : ``int``
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

    wavelength: int = field(
        validator=validators.instance_of(int),
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

    wavecolor: str = field(
        init=False,
        metadata={"description": "Hexadecimal representation of the light color."},
    )

    def __attrs_post_init__(self) -> None:
        self.wavecolor = wavelength_to_hex(self.wavelength)


def wavelength_to_hex(wavelength: int) -> str:
    """Convert a wavelength in nanometers to an RGB color in hexadecimal format."""

    def adjust(color: float, factor: float) -> int:
        """Adjust the color intensity by the given factor and convert to integer."""
        return max(0, min(255, int(round(color * factor))))

    if wavelength < 380 or wavelength > 780:
        return "#000000"  # Return black for wavelengths outside visible spectrum

    r, g, b = 0.0, 0.0, 0.0

    if 380 <= wavelength < 440:
        r = -(wavelength - 440) / (440 - 380)
        g = 0.0
        b = 1.0
    elif 440 <= wavelength < 490:
        r = 0.0
        g = (wavelength - 440) / (490 - 440)
        b = 1.0
    elif 490 <= wavelength < 510:
        r = 0.0
        g = 1.0
        b = -(wavelength - 510) / (510 - 490)
    elif 510 <= wavelength < 580:
        r = (wavelength - 510) / (580 - 510)
        g = 1.0
        b = 0.0
    elif 580 <= wavelength < 645:
        r = 1.0
        g = -(wavelength - 645) / (645 - 580)
        b = 0.0
    elif 645 <= wavelength <= 780:
        r = 1.0
        g = 0.0
        b = 0.0

    factor = 1.0
    if wavelength < 420:
        factor = 0.3 + 0.7 * (wavelength - 380) / (420 - 380)
    elif wavelength > 700:
        factor = 0.3 + 0.7 * (780 - wavelength) / (780 - 700)

    r = adjust(r, factor)
    g = adjust(g, factor)
    b = adjust(b, factor)

    return f"#{r:02x}{g:02x}{b:02x}"
