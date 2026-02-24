"""Utilities for device implementations."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from attrs import Attribute


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


def has_only_one_key(
    instance: object,
    attribute: Attribute[dict[str, dict[str, str]]],
    value: dict[str, dict[str, str]],
) -> None:
    if len(value.keys()) > 1:
        raise ValueError(
            "The first level of the nested dictionary must contain only one key."
        )


def convert_shape(value: Sequence[int] | None) -> tuple[int, int]:
    """Convert an input sequence to a tuple of ints.

    Used for converting the sensor shape from the configuration file.

    Parameters
    ----------
    value : ``Any``
        Value to convert.

    Returns
    -------
    ``tuple[int, ...]``
        Tuple of ints.

    """
    if value is None:
        return (0, 0)

    if len(value) != 2:
        raise ValueError("The tuple must contain exactly two values.")
    else:
        return (int(value[0]), int(value[1]))


def check_limits(
    instance: object,
    attribute: Attribute[dict[str, tuple[float, float]]],
    value: dict[str, tuple[float, float]] | None,
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
