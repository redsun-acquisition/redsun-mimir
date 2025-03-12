from __future__ import annotations

import math
from typing import TYPE_CHECKING

from bluesky.protocols import Descriptor, Location, Reading
from sunflare.engine import Status

from ..protocols import LightProtocol

if TYPE_CHECKING:
    from typing import Any

    from ._config import LightModelInfo, StageModelInfo


class MockLightModel(LightProtocol):
    """Mock light source for simulation and testing purposes."""

    def __init__(self, name: str, model_info: LightModelInfo) -> None:
        self._name = name
        self._model_info = model_info
        self.enabled = False
        self.intensity = 0.0

    def set(self, value: Any, **kwargs: Any) -> Status:
        """Set the intensity of the light source.

        .. note::

            **kwargs are ignored in this implementation.

        """
        if not isinstance(value, (int, float)):
            raise ValueError("Value must be a number.")
        s = Status()
        self.intensity = float(value)
        s.set_finished()
        return s

    def read_configuration(self) -> dict[str, Reading[Any]]:
        return self.model_info.read_configuration()

    def describe_configuration(self) -> dict[str, Descriptor]:
        return self.model_info.describe_configuration()

    def shutdown(self) -> None: ...

    def trigger(self) -> Status:
        """Toggle the activation status of the light source."""
        self.enabled = not self.enabled
        s = Status()
        s.set_finished()
        return s

    @property
    def name(self) -> str:
        return self._name

    @property
    def parent(self) -> None:
        return None

    @property
    def model_info(self) -> LightModelInfo:
        return self._model_info


class MockStageModel:
    """Mock stage model for testing purposes."""

    def __init__(self, name: str, model_info: StageModelInfo) -> None:
        self._name = name
        self._model_info = model_info
        self._positions: dict[str, Location[float]] = {
            axis: Location(setpoint=0.0, readback=0.0) for axis in model_info.axis
        }

        # set the current axis to the first axis
        self.axis = self._model_info.axis[0]

        self._step_sizes = self._model_info.step_sizes

    def set(self, value: Any, **kwargs: Any) -> Status:
        """Set something in the mock model.

        Either set the motor position or update a configuration value.
        When setting a configuration value, the keyword argument `prop`
        must be provided.
        Accepted updatable properties:

        - ``axis``: motor axis.

        i.e. `set(10)` will set the motor position to 10,
        `set("Y", prop="axis")` will update the axis to "Y".

        Parameters
        ----------
        value : ``Any``
            New value to set.
        **kwargs : ``Any``
            Additional keyword arguments.

        Returns
        -------
        ``Status``
            The status object.
            For this mock model, it will always be set to finished.
            If ``value`` is not of type ``float``,
            the status will set a ``ValueError`` exception.

        """
        s = Status()
        propr = kwargs.get("prop", None)
        if propr == "axis" and isinstance(value, str):
            self.axis = value
            s.set_finished()
            return s
        else:
            if not isinstance(value, (int, float)):
                s.set_exception(ValueError("Value must be a float or int."))
                return s
        steps = math.floor(
            (value - self._positions[self.axis]["setpoint"])
            / self._step_sizes[self.axis]
        )
        for _ in range(steps):
            self._positions[self.axis]["setpoint"] += self._step_sizes[self.axis]
        s.set_finished()
        s.add_callback(self._set_readback)
        return s

    def locate(self) -> Location[float]:
        """Locate mock model."""
        return self._positions[self.axis]

    def read_configuration(self) -> dict[str, Reading[Any]]:
        """Read mock configuration."""
        return self.model_info.read_configuration()

    def describe_configuration(self) -> dict[str, Descriptor]:
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
        self._positions[self.axis]["readback"] = self._positions[self.axis]["setpoint"]
