from __future__ import annotations

from typing import TYPE_CHECKING

from attrs import define, field, setters, validators
from sunflare.config import ModelInfo

if TYPE_CHECKING:
    from typing import Any, Iterable, Optional, Union


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


@define
class Specimen:
    """Container for specimen information.

    It is used in conjunction with
    :class:``openwfs.simulation.StaticSource``
    to generate a fake moving sample.

    Parameters
    ----------
    resolution: ``tuple[int, int]``
        Specimen resolution in pixels (height, width).
    pixel_size: ``float``
        Pixel size in nanometers.
    magnification: ``int``
        # Magnification from object plane to camera.
    numerical_aperture: ``float``
        Numerical aperture of the microscope objective.
    wavelength: ``float``
        Wavelength of the light source in nanometers.

    """

    resolution: tuple[int, int] = field(converter=tuple, on_setattr=setters.frozen)
    pixel_size: float = field(
        validator=validators.instance_of(float), on_setattr=setters.frozen
    )
    magnification: int = field(validator=validators.instance_of(int))
    numerical_aperture: float = field(validator=validators.instance_of(float))
    wavelength: float = field(validator=validators.instance_of(float))

    @resolution.validator
    def _validate_resolution(self, _: tuple[int, ...], value: tuple[int, ...]) -> None:
        if not all(isinstance(val, int) for val in value):
            raise ValueError("All values in the tuple must be integers.")
        if len(value) != 2:
            raise ValueError("The tuple must contain exactly two values.")


def convert_specimen_obj(
    x: Optional[Union[Specimen, dict[str, Any]]],
) -> Optional[Specimen]:
    """Convert a dictionary to a Specimen object.

    If the input is already a Specimen object, return as is.

    Parameters
    ----------
    x : ``Any``
        Input to convert.

    Returns
    -------
    ``Optional[Specimen]``
        Specimen object.

    """
    if x is not None:
        if isinstance(x, Specimen):
            return x
        else:
            return Specimen(**x)
    return None


@define(kw_only=True)
class DetectorModelInfo(ModelInfo):
    """Configuration of a detector model.

    specimen: ``Specimen``, optional
        Information about the specimen.
        Used by the OpenWFS simulator.
    """

    specimen: Optional[Specimen] = field(
        default=None,
        converter=convert_specimen_obj,
    )
    sensor_shape: tuple[int, int] = field(converter=tuple, on_setattr=setters.frozen)
    pixel_size: tuple[float, float, float] = field(
        converter=tuple, on_setattr=setters.frozen
    )

    @sensor_shape.validator
    def _validate_sensor_shape(
        self, _: tuple[int, ...], value: tuple[int, ...]
    ) -> None:
        if not all(isinstance(val, int) for val in value):
            raise ValueError("All values in the tuple must be integers.")
        if len(value) != 2:
            raise ValueError("The tuple must contain exactly two values.")

    @pixel_size.validator
    def _validate_pixel_size(
        self, _: tuple[float, ...], value: tuple[float, ...]
    ) -> None:
        if not all(isinstance(val, float) for val in value):
            raise ValueError("All values in the tuple must be floats.")
        if len(value) != 3:
            raise ValueError("The tuple must contain exactly three values.")
