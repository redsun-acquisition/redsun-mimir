from __future__ import annotations

from typing import TYPE_CHECKING

from attrs import define, field, setters, validators
from sunflare.config import ModelInfo

if TYPE_CHECKING:
    from typing import Any, Iterable, Optional, Union


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


def convert_limits(
    value: Optional[dict[str, list[float]]],
) -> Optional[dict[str, tuple[float, ...]]]:
    if value is None:
        return None
    return {
        axis: tuple((float(val) for val in limits)) for axis, limits in value.items()
    }


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
    limits: ``dict[str, tuple[float, float]]``, optional
        Limits for each axis.
        (i.e. {"X": (0.0, 100.0), "Y": (0.0, 100.0), "Z": (0.0, 100.0)})
        Default is ``None`` (no limits).

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
    limits: Optional[dict[str, tuple[float, float]]] = field(
        default=None,
        converter=convert_limits,
        metadata={"description": "Limits for each axis."},
    )

    @limits.validator
    def _check_limits(
        self, _: str, value: Optional[dict[str, tuple[float, float]]]
    ) -> None:
        if value is None:
            return
        for axis, limits in value.items():
            if len(limits) != 2:
                raise AttributeError(
                    f"Length of limits must be 2: {axis} has length {len(limits)}"
                )
            if limits[0] > limits[1]:
                raise AttributeError(
                    f"{axis} minimum limit is greater than the maximum limit: {limits}"
                )


@define(kw_only=True)
class LightModelInfo(ModelInfo):
    """Configuration of a light model.

    .. note::

        If the light source operates in binary mode (ON/OFF),
        the assumption is that the light source will be started
        in an ``OFF`` state.

    Parameters
    ----------
    binary: ``bool``
        If the light source operates
        in binary mode (ON/OFF). Default is False.
    wavelength : ``int``
        Wavelength in nm.
        Default to 0 (wavelength not set).
    egu : ``str``
        Engineering units. Default is "mW".
        Unused if binary is True.
    intensity_range : ``tuple[float, float]``
        Intensity range (min, max). Unused if binary is True.
    step_size : ``int``
        Step size for the intensity. Default is 1.
        Unused if binary is True.

    """

    binary: bool = field(
        default=False,
        validator=validators.instance_of(bool),
        metadata={"description": "Binary mode operation."},
    )
    wavelength: int = field(
        default=0,
        validator=validators.instance_of(int),
        metadata={"description": "Wavelength in nm."},
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
        Magnification from object plane to camera.
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
