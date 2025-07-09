from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypedDict

if TYPE_CHECKING:
    from bluesky.protocols import Descriptor, Reading


class ConfigurationDict(TypedDict):
    """TypedDict grouping configuration data."""

    descriptors: dict[str, dict[str, "Descriptor"]]
    readings: dict[str, dict[str, "Reading[Any]"]]
