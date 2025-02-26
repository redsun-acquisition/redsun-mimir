from __future__ import annotations

from typing import Iterable, Optional

import numpy as np
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


def to_float_tuple(value: Optional[Iterable[float]]) -> tuple[float, ...]:
    """Convert a value to a tuple of floats.

    If the value is ``None``, return a tuple of two zeros.
    A validator should take care of checking the actual
    value in respect to other constraints.

    Parameters
    ----------
    value : ``Any``
        Value to convert.

    Returns
    -------
    ``tuple[float, float]``
        Tuple of floats. ``(0.0, 0.0)`` if value is ``None``.

    """
    if value is None:
        return (0.0, 0.0)
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"Expected a list or tuple of length 2, got {value}")
    return tuple(float(v) for v in value)


@define(kw_only=True)
class LightModelInfo(ModelInfo):
    """Configuration of a light model.

    .. note::

        If the light source operates in binary mode (ON/OFF),
        the assumption is that the light source will be started
        in an ``OFF`` state.

    Parameters
    ----------
    wavelength : ``int``
        Wavelength in nm.
    binary: ``bool``, optional
        If the light source operates
        in binary mode (ON/OFF). Default is False.
    egu : ``str``, optional
        Engineering units. Default is "mW".
        Unused if binary is True.
    intensity_range : ``tuple[float, float]``, optional
        Intensity range (min, max). Unused if binary is True.
    step_size : ``int``, optional
        Step size for the intensity. Default is 1.
        Unused if binary is True.

    """

    wavelength: int = field(
        validator=validators.instance_of(int),
        metadata={"description": "Wavelength in nm."},
    )
    binary: bool = field(
        default=False,
        validator=validators.instance_of(bool),
        metadata={"description": "Binary mode operation."},
    )
    egu: str = field(
        default="mW",
        validator=validators.instance_of(str),
        on_setattr=setters.frozen,
        metadata={"description": "Engineering units."},
    )
    intensity_range: tuple[float, float] = field(
        default=None,
        converter=to_float_tuple,
        metadata={"description": "Intensity range (min, max)."},
    )
    step_size: int = field(
        default=1,
        validator=validators.instance_of(int),
        metadata={"description": "Step size for the intensity."},
    )

    @intensity_range.validator
    def _check_range(self, _: str, value: tuple[float, float]) -> None:
        if self.binary and value == (0.0, 0.0):
            return
        if value[0] > value[1]:
            raise AttributeError(f"Min value is greater than max value: {value}")


# this has to be tested at some point
def wavelength_to_hex(wavelength: int) -> str:  # pragma: no cover
    """Convert a wavelength in nanometers (nm) to an RGB hex string.

    Parameters
    ----------
    wavelength: int
        Wavelength in nanometers.

    Returns
    -------
    ``str``
        Hex string representation of the RGB color.

    """
    # Ensure the input is within the visible spectrum
    wavelength = np.clip(wavelength, 380, 780)

    r, g, b = 0.0, 0.0, 0.0

    if 380 <= wavelength < 440:
        r = -(wavelength - 440) / (440 - 380)
        b = 1.0
    elif 440 <= wavelength < 490:
        g = (wavelength - 440) / (490 - 440)
        b = 1.0
    elif 490 <= wavelength < 510:
        g = 1.0
        b = -(wavelength - 510) / (510 - 490)
    elif 510 <= wavelength < 580:
        r = (wavelength - 510) / (580 - 510)
        g = 1.0
    elif 580 <= wavelength < 645:
        r = 1.0
        g = -(wavelength - 645) / (645 - 580)
    elif 645 <= wavelength <= 780:
        r = 1.0

    if 380 <= wavelength < 420:
        factor = 0.3 + 0.7 * (wavelength - 380) / (420 - 380)
    elif 645 <= wavelength <= 780:
        factor = 0.3 + 0.7 * (780 - wavelength) / (780 - 645)
    else:
        factor = 1.0

    rgb = np.array([r, g, b]) * factor
    rgb = (np.round(rgb * 255)).astype(int)

    return "#{:02x}{:02x}{:02x}".format(rgb[0], rgb[1], rgb[2])
