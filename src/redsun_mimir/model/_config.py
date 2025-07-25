from __future__ import annotations

from typing import TYPE_CHECKING

from attrs import define, field, setters, validators
from sunflare.config import ModelInfo

if TYPE_CHECKING:
    from collections.abc import Iterable

    from bluesky.protocols import Descriptor


def convert_to_tuple(value: Iterable[float | int] | None) -> tuple[int | float, ...]:
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
    return tuple(v for v in value)


def convert_limits(
    value: dict[str, list[float]] | None,
) -> dict[str, tuple[float, ...]] | None:
    if value is None:
        return None
    return {axis: tuple(float(val) for val in limits) for axis, limits in value.items()}


@define(kw_only=True)
class MotorModelInfo(ModelInfo):
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
    limits: dict[str, tuple[float, float]] | None = field(
        default=None,
        converter=convert_limits,
        metadata={"description": "Limits for each axis."},
    )

    @limits.validator
    def _check_limits(
        self, _: str, value: dict[str, tuple[float, float]] | None
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
    intensity_range: tuple[int | float, ...] = field(
        default=None,
        converter=convert_to_tuple,
        metadata={"description": "Intensity range (min, max)."},
    )
    step_size: int = field(
        default=1,
        validator=validators.instance_of(int),
        metadata={"description": "Step size for the intensity."},
    )

    @intensity_range.validator
    def _check_range(self, _: str, value: tuple[int | float, ...]) -> None:
        if self.binary and value == (0.0, 0.0):
            return
        if len(value) != 2:
            raise AttributeError(
                f"Length of intensity range must be 2: {value} has length {len(value)}"
            )
        if not all(isinstance(val, (float, int)) for val in value):
            raise AttributeError(
                f"All values in the intensity range must be floats or ints: {value}"
            )
        if value[0] > value[1]:
            raise AttributeError(f"Min value is greater than max value: {value}")


def convert_to_float(value: Iterable[float]) -> tuple[float, ...]:
    """Convert a value to a tuple of floats.

    Parameters
    ----------
    value : ``Any``
        Value to convert.

    Returns
    -------
    ``tuple[float, ...]``
        Tuple of floats.

    """
    return tuple(float(val) for val in value)


@define(kw_only=True)
class DetectorModelInfo(ModelInfo):
    """Configuration of a detector model.

    Parameters
    ----------
    sensor_shape : ``tuple[int, int]``
        Shape of the sensor in pixels (height, width).
    pixel_size : ``tuple[float, ...]``
        Sensor pixel size in micrometers.
    """

    sensor_shape: tuple[int, int] = field(converter=tuple)
    pixel_size: tuple[float, ...] = field(
        converter=convert_to_float, on_setattr=setters.frozen
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
            raise ValueError("All pixel sizes must be floats.")
        if len(value) < 1 and len(value) > 3:
            raise ValueError("Pixel size must contain between 1 and 3 values.")

    def describe_configuration(
        self, source: str = "model_info"
    ) -> dict[str, Descriptor]:
        config: dict[str, Descriptor] = super().describe_configuration(source)
        config["pixel_size"]["units"] = "μm"
        return config
