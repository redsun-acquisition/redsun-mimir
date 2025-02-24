from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from bluesky.protocols import Location, Reading
from sunflare.engine import Status

if TYPE_CHECKING:
    from event_model.documents.event_descriptor import DataKey

    from ..config import StageModelInfo


class MockStageModel:
    """Mock stage model for testing purposes."""

    def __init__(self, name: str, model_info: StageModelInfo) -> None:
        self._name = name
        self._model_info = model_info
        self._positions: dict[str, Location[float]] = {
            axis: Location(setpoint=0.0, readback=0.0) for axis in model_info.axis
        }

        # set the current axis to the first axis
        self._axis = self._model_info.axis[0]

        self._step_sizes = self._model_info.step_sizes

    def set(self, value: float) -> Status:
        """Set mock model position."""
        s = Status()
        steps = math.floor(
            (value - self._positions[self._axis]["setpoint"])
            / self._step_sizes[self._axis]
        )
        for _ in range(steps):
            self._positions[self._axis]["setpoint"] += self._step_sizes[self._axis]
        s.set_finished()
        s.add_callback(self._set_readback)
        return s

    def locate(self) -> Location[float]:
        """Locate mock model."""
        return self._positions[self._axis]

    def configure(self, *_: Any, **kwargs: Any) -> tuple[Reading[Any], Reading[Any]]:
        """Configure the mock model.

        Parameters
        ----------
        kwargs : dict
            Configuration parameters.
            Accepted values:
            - ``axis``: axis name.

        Returns
        -------
        ``tuple[Reading, Reading]``
            Old and new configuration readings.

        Raises
        ------
        ``KeyError``
            Invalid configuration key.

        """
        if "axis" in kwargs:
            old = Reading(value=self._axis, timestamp=0)
            self._axis = kwargs["axis"]
            new = Reading(value=self._axis, timestamp=0)
            return old, new
        else:
            raise KeyError("Invalid configuration key")

    def read_configuration(self) -> dict[str, Reading[Any]]:
        """Read mock configuration."""
        return self.model_info.read_configuration()

    def describe_configuration(self) -> dict[str, DataKey]:
        """Describe mock configuration."""
        return self.model_info.describe_configuration()

    @property
    def parent(self) -> None:
        return None

    @property
    def name(self) -> str:  # noqa: D102
        return self._name

    @property
    def model_info(self) -> StageModelInfo:  # noqa: D102
        return self._model_info

    def shutdown(self) -> None: ...

    def _set_readback(self, _: Status) -> None:
        """Simulate the motor moving to the setpoint via a callback.

        Parameters
        ----------
        s : Status
            The status object (not used).
        axis : str
            Axis name.

        """
        self._positions[self._axis]["readback"] = self._positions[self._axis][
            "setpoint"
        ]
