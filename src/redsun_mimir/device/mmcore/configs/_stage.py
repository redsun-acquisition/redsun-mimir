from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from typing import TypedDict


class StageConfigDict(TypedDict):
    adapter: str
    device: str
    axis: list[str]
    limits: dict[str, tuple[float, float]]
    step_sizes: dict[str, float]


@dataclass(frozen=True)
class BaseStageConfig(ABC):
    """Base configuration dataclass for MMCoreStageDevice."""

    adapter: str
    """Adapter name for the stage device."""

    device: str
    """Device name for the stage device."""

    egu: str = "um"
    """Engineering units for the stage position."""

    axis: list[str] = field(default_factory=list)
    """List of stage axes to control (e.g., ["X", "Y"] or ["Z"])."""

    limits: dict[str, tuple[float, float]] = field(default_factory=dict)
    """Mapping of axis names to their movement limits (min, max)."""

    step_sizes: dict[str, float] = field(default_factory=dict)
    """Mapping of axis names to their step sizes in microns."""

    def dump(self) -> StageConfigDict:
        """Dump the stage configuration to a dictionary."""
        return {
            "adapter": self.adapter,
            "device": self.device,
            "axis": self.axis,
            "limits": self.limits,
            "step_sizes": self.step_sizes,
        }


@dataclass(frozen=True)
class DemoXYStageConfig(BaseStageConfig):
    """Example configuration for a demo XY stage device."""

    adapter: str = "DemoCamera"
    device: str = "DXYStage"
    axis: list[str] = field(default_factory=lambda: ["x", "y"])

    # inspected from mmcore c++ source code
    limits: dict[str, tuple[float, float]] = field(
        default_factory=lambda: {"x": (0, 20_000.0), "y": (0, 20_000.0)}
    )
    step_sizes: dict[str, float] = field(
        default_factory=lambda: {"x": 0.015, "y": 0.015}
    )


@dataclass(frozen=True)
class DemoZStageConfig(BaseStageConfig):
    """Example configuration for a demo Z stage device."""

    adapter: str = "DemoCamera"
    device: str = "DStage"
    axis: list[str] = field(default_factory=lambda: ["z"])

    # inspected from mmcore c++ source code
    limits: dict[str, tuple[float, float]] = field(
        default_factory=lambda: {"z": (-300.0, 300.0)}
    )
    step_sizes: dict[str, float] = field(default_factory=lambda: {"z": 0.025})
