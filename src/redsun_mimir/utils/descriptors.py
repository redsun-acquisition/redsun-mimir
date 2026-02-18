r"""Helper utilities for building bluesky-compatible descriptor and reading keys.

Key format
----------
Keys follow the convention::

    {prefix}:{name}\{property}

where:

- ``prefix`` is a short device-class tag (e.g. ``"MM"`` for Micro-Manager).
- ``name``   is the runtime device instance name (e.g. ``"mmcore"``).
- ``property`` is the individual setting name (e.g. ``"exposure"``).

Example: ``MM:mmcore\exposure``

The same key convention applies to both configuration descriptor dicts
(``describe_configuration()``) and configuration reading dicts
(``read_configuration()``), so that the same ``parse_key`` / ``make_key``
helpers can be reused uniformly across both.

These helpers are intended to be ported to ``sunflare`` once the API
stabilises.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, TypeVar, overload

if TYPE_CHECKING:
    from bluesky.protocols import Descriptor, Reading
    from event_model.documents import LimitsRange

__all__ = [
    "make_key",
    "parse_key",
    "make_descriptor",
    "make_reading",
]

T = TypeVar("T")


def make_key(prefix: str, name: str, property_name: str) -> str:
    r"""Build a canonical device property key.

    Parameters
    ----------
    prefix :
        Short device-class tag (e.g. ``"MM"``).
    name :
        Runtime device instance name (e.g. ``"mmcore"``).
    property_name :
        Individual setting name (e.g. ``"exposure"``).
        Nested properties use "\\" as separator
        (e.g. ``r"step_size\X"`` for per-axis step sizes).

    Returns
    -------
    str
        Key in the form ``{prefix}:{name}\{property_name}``.
    """
    return f"{prefix}:{name}\\{property_name}"


def parse_key(key: str) -> tuple[str, str, str]:
    r"""Parse a canonical device property key into its components.

    Parameters
    ----------
    key :
        Key in the form ``{prefix}:{name}\{property_name}``.

    Returns
    -------
    tuple[str, str, str]
        ``(prefix, name, property_name)``

    Raises
    ------
    ValueError
        If the key does not conform to the expected format.
    """
    try:
        prefix_name, property_name = key.split("\\", 1)
        prefix, name = prefix_name.split(":", 1)
        return prefix, name, property_name
    except ValueError:
        raise ValueError(
            f"Key {key!r} does not conform to the expected "
            f"'{{prefix}}:{{name}}\\{{property}}' format."
        )


@overload
def make_descriptor(
    source: str,
    dtype: Literal["number"],
    *,
    low: float | None = ...,
    high: float | None = ...,
    units: str | None = ...,
) -> Descriptor: ...
@overload
def make_descriptor(
    source: str,
    dtype: Literal["integer"],
    *,
    low: int | None = ...,
    high: int | None = ...,
    units: str | None = ...,
) -> Descriptor: ...
@overload
def make_descriptor(
    source: str,
    dtype: Literal["string"],
    *,
    choices: list[str] | None = ...,
    units: str | None = ...,
) -> Descriptor: ...
@overload
def make_descriptor(
    source: str,
    dtype: Literal["array"],
    *,
    shape: list[int | None] = ...,
    units: str | None = ...,
) -> Descriptor: ...
def make_descriptor(
    source: str,
    dtype: Literal["number", "integer", "string", "array"],
    *,
    low: float | int | None = None,
    high: float | int | None = None,
    units: str | None = None,
    choices: list[str] | None = None,
    shape: list[int | None] | None = None,
) -> Descriptor:
    r"""Build a bluesky-compatible descriptor entry.

    This is the single entry-point for all descriptor construction.
    Select the desired ``dtype`` and supply the matching keyword arguments;
    the type-checker enforces that only valid combinations are used.

    Parameters
    ----------
    source : str
        Human-readable source label (e.g. ``"settings"``, ``"properties"``).
    dtype : Literal["number", "integer", "string", "array"]
        One of ``"number"``, ``"integer"``, ``"string"``, ``"array"``.
    low : float | int | None
        Lower control limit. Valid for ``"number"`` and ``"integer"`` only.
        Both ``low`` and ``high`` must be provided together.
    high : float | int | None
        Upper control limit. Valid for ``"number"`` and ``"integer"`` only.
    units : str | None
        Physical unit string (e.g. ``"ms"``, ``"nm"``).
        Valid for ``"number"`` and ``"integer"`` only.
    choices : list[str] | None
        Allowed string values for combo-box editing.
        Valid for ``"string"`` only; produces an enum-style descriptor.
    shape : list[int | None] | None
        Array dimensions. Required for ``"array"``.
        A `None` entry indicates a variable dimension (e.g. ``[None, 3]`` for an Nx3 array).

    Returns
    -------
    Descriptor
        The constructed descriptor dictionary.

    Examples
    --------
    Floating-point with limits and units::

        make_descriptor("settings", "number", low=0.0, high=1000.0, units="ms")

    Integer without limits::

        make_descriptor("settings", "integer", units="nm")

    Free-text string::

        make_descriptor("settings", "string")

    Enumerated string::

        make_descriptor("settings", "string", choices=["8bit", "16bit", "32bit"])

    Fixed-shape array::

        make_descriptor("settings", "array", shape=[2])
    """
    d: Descriptor = {"source": source, "dtype": dtype, "shape": []}
    if units is not None:
        d["units"] = units

    match dtype:
        case "number" | "integer":
            if low is not None and high is not None:
                limits: LimitsRange = {"low": float(low), "high": float(high)}
                d["limits"] = {"control": limits}
            if units is not None:
                d["units"] = units
        case "string":
            if choices is not None:
                d["choices"] = choices
        case "array":
            if shape is None:
                raise ValueError("'shape' is required when dtype='array'.")
            d["shape"] = shape
    return d


def make_reading(value: T, timestamp: float) -> Reading[T]:
    """Build a bluesky-compatible reading entry.

    Parameters
    ----------
    value : T
        Current value for the property.
    timestamp : float
        UNIX timestamp of the reading.

    Returns
    -------
    Reading[T]
    """
    return {"value": value, "timestamp": timestamp}
