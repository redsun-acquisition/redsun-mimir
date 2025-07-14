from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Generic, TypeVar

if TYPE_CHECKING:
    from sunflare.containers._registry import ParameterInfo

T = TypeVar("T")


@dataclass(frozen=True)
class Meta(Generic[T]):
    """Metadata for a plan parameter.

    Parameters
    ----------
    min : T | None, optional
        Minimum value for a parameter.
    max : T | None, optional
        Maximum value for a parameter.
    choices : list[str], optional
        List of possible choices for a parameter value.
        Useful to restrict, for example, the devics
        that can be selected by a widget.
    """

    min: T | None = None
    max: T | None = None
    choices: list[str] | None = None


@dataclass(frozen=True)
class ParameterManifest:
    """Manifest describing how to create a widget for a plan parameter."""

    name: str
    param_info: ParameterInfo
    choices: list[str] | None = None  # For combobox parameters
    min_value: float | None = None  # For numeric parameters
    max_value: float | None = None  # For numeric parameters
    default_value: Any = None


@dataclass(frozen=True)
class PlanManifest:
    """Complete manifest for generating UI for a plan."""

    name: str
    display_name: str
    description: str
    parameters: dict[str, ParameterManifest]
    is_toggleable: bool = False  # For continuous plans like live_count
