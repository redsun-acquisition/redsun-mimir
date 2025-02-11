from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any

from sunflare.engine import Status
from sunflare.model import ModelProtocol

import numpy as np

if TYPE_CHECKING:
    from bluesky.protocols import Location, Reading
    from event_model.documents.event_descriptor import DataKey

    from .config import StageModelInfo


class MockStageModel(ModelProtocol):
    """Mock stage model for testing purposes."""

    def __init__(self, name: str, model_info: StageModelInfo) -> None:
        self._name = name
        self._model_info = model_info
        self._positions: dict[str, Location[float]] = {
            axis: Location(setpoint=0.0, readback=0.0) for axis in model_info.axis
        }

        self._step_sizes = self._model_info.step_sizes

    def set(self, value: float, /, axis: str) -> Status:
        """Set mock model."""
        s = Status()
        s.add_callback(partial(self._wait_readback, axis=axis))
        steps = np.floor(
            (value - self._positions[axis]["setpoint"]) / self._step_sizes[axis]
        ).astype(float)
        for _ in range(steps):
            self._positions[axis]["setpoint"] += self._step_sizes[axis]
        s.set_finished()
        return s

    def locate(self, /, axis: str) -> Location[float]:
        """Locate mock model."""
        return self._positions[axis]

    def configure(self, name: str, value: Any, /, **kwargs: Any) -> None:
        """Configure mock model."""
        setattr(self.model_info, name, value)

    def read_configuration(self) -> dict[str, Reading[Any]]:
        """Read mock configuration."""
        return self.describe_configuration()

    def describe_configuration(self) -> dict[str, DataKey]:
        """Describe mock configuration."""
        return self.model_info.describe_configuration()

    @property
    def name(self) -> str:  # noqa: D102
        return self._name

    @property
    def model_info(self) -> StageModelInfo:  # noqa: D102
        return self._model_info

    def _wait_readback(self, _: Status, axis: str) -> None:
        """Simulate the motor moving to the setpoint via a callback.

        Parameters
        ----------
        s : Status
            The status object (not used).
        axis : str
            Axis name.

        """
        self._positions[axis]["readback"] = self._positions[axis]["setpoint"]
