"""Helper utilities for building bluesky-compatible descriptor and reading keys.

Key format
----------
Keys follow the convention::

    {prefix}:{name}\\{property}

where:

- ``prefix`` is a short device-class tag (e.g. ``"MM"`` for Micro-Manager).
- ``name``   is the runtime device instance name (e.g. ``"mmcore"``).
- ``property`` is the individual setting name (e.g. ``"exposure"``).

Example: ``MM:mmcore\\exposure``

These helpers are intended to be ported to ``sunflare`` once the API
stabilises.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

    from bluesky.protocols import Descriptor, Reading
    from event_model.documents import LimitsRange

__all__ = [
    "make_key",
    "make_number_descriptor",
    "make_integer_descriptor",
    "make_string_descriptor",
    "make_enum_descriptor",
    "make_array_descriptor",
    "make_reading",
]

# ---------------------------------------------------------------------------
# Key construction
# ---------------------------------------------------------------------------


def make_key(prefix: str, name: str, property_name: str) -> str:
    """Build a canonical device property key.

    Parameters
    ----------
    prefix :
        Short device-class tag (e.g. ``"MM"``).
    name :
        Runtime device instance name (e.g. ``"mmcore"``).
    property_name :
        Individual setting name (e.g. ``"exposure"``).

    Returns
    -------
    str
        Key in the form ``{prefix}:{name}\\{property_name}``.
    """
    return f"{prefix}:{name}\\{property_name}"


def parse_key(key: str) -> tuple[str, str, str]:
    """Parse a canonical device property key into its components.

    Parameters
    ----------
    key :
        Key in the form ``{prefix}:{name}\\{property_name}``.

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


# ---------------------------------------------------------------------------
# Descriptor factories
# ---------------------------------------------------------------------------


def make_number_descriptor(
    source: str,
    *,
    low: float | None = None,
    high: float | None = None,
    units: str | None = None,
) -> Descriptor:
    """Build a floating-point number descriptor.

    Parameters
    ----------
    source :
        Human-readable source label (e.g. ``"settings"``).
    low :
        Lower control limit. Omitted from descriptor when ``None``.
    high :
        Upper control limit. Omitted from descriptor when ``None``.
    units :
        Physical unit string (e.g. ``"ms"``). Omitted when ``None``.

    Returns
    -------
    Descriptor
    """
    d: dict[str, Any] = {"source": source, "dtype": "number", "shape": []}
    if low is not None and high is not None:
        limits: LimitsRange = {"low": low, "high": high}
        d["limits"] = {"control": limits}
    if units is not None:
        d["units"] = units
    return d  # type: ignore[return-value]


def make_integer_descriptor(
    source: str,
    *,
    low: int | None = None,
    high: int | None = None,
    units: str | None = None,
) -> Descriptor:
    """Build an integer descriptor.

    Parameters
    ----------
    source :
        Human-readable source label.
    low :
        Lower control limit.
    high :
        Upper control limit.
    units :
        Physical unit string.

    Returns
    -------
    Descriptor
    """
    d: dict[str, Any] = {"source": source, "dtype": "integer", "shape": []}
    if low is not None and high is not None:
        limits: LimitsRange = {"low": float(low), "high": float(high)}
        d["limits"] = {"control": limits}
    if units is not None:
        d["units"] = units
    return d  # type: ignore[return-value]


def make_string_descriptor(source: str) -> Descriptor:
    """Build a free-text string descriptor.

    Parameters
    ----------
    source :
        Human-readable source label.

    Returns
    -------
    Descriptor
    """
    d: dict[str, Any] = {"source": source, "dtype": "string", "shape": []}
    return d  # type: ignore[return-value]


def make_enum_descriptor(source: str, choices: list[str]) -> Descriptor:
    """Build an enumerated string descriptor.

    Parameters
    ----------
    source :
        Human-readable source label.
    choices :
        Allowed string values shown in the combo-box editor.

    Returns
    -------
    Descriptor
    """
    d: dict[str, Any] = {
        "source": source,
        "dtype": "string",
        "shape": [],
        "choices": choices,
    }
    return d  # type: ignore[return-value]


def make_array_descriptor(source: str, shape: list[int]) -> Descriptor:
    """Build an array descriptor (read-only in the tree view).

    Parameters
    ----------
    source :
        Human-readable source label.
    shape :
        Array dimensions.

    Returns
    -------
    Descriptor
    """
    d: dict[str, Any] = {"source": source, "dtype": "array", "shape": shape}
    return d  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Reading factory
# ---------------------------------------------------------------------------


def make_reading(value: Any, timestamp: float) -> Reading[Any]:
    """Build a bluesky-compatible reading entry.

    Parameters
    ----------
    value :
        Current value for the property.
    timestamp :
        UNIX timestamp of the reading.

    Returns
    -------
    Reading[Any]
    """
    return {"value": value, "timestamp": timestamp}
