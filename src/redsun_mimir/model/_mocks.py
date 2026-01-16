from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING

from sunflare.engine import Status
from sunflare.log import Loggable

from redsun_mimir.protocols import LightProtocol, MotorProtocol

if TYPE_CHECKING:
    from typing import Any

    from bluesky.protocols import Descriptor, Location, Reading

    from ._config import LightModelInfo, MotorModelInfo


class MockLightModel(LightProtocol, Loggable):
    """Mock light source for simulation and testing purposes."""

    def __init__(self, name: str, model_info: LightModelInfo) -> None:
        self._name = name
        self._model_info = model_info
        self.enabled = False
        self.intensity = 0.0
        self.logger.info("Initialized")

    def set(self, value: Any, **kwargs: Any) -> Status:
        """Set the intensity of the light source.

        Parameters
        ----------
        value : ``Any``
            New intensity value. Must be of type ``int`` or ``float``.
        **kwargs : ``Any``
            Additional keyword arguments (not used).

        Returns
        -------
        ``Status``
            The status object.
        """
        s = Status()
        if not isinstance(value, int | float):
            s.set_exception(ValueError("Value must be a number."))
            return s
        self.intensity = float(value)
        s.set_finished()
        return s

    def describe(self) -> dict[str, Descriptor]:
        return {
            "intensity": {
                "source": self.name,
                "dtype": "number",
                "shape": [],
            },
            "enabled": {
                "source": self.name,
                "dtype": "boolean",
                "shape": [],
            },
        }

    def read(self) -> dict[str, Reading[Any]]:
        return {
            "intensity": {"value": self.intensity, "timestamp": time.time()},
            "enabled": {"value": self.enabled, "timestamp": time.time()},
        }

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


class MockMotorModel(MotorProtocol, Loggable):
    """Mock stage model for testing purposes."""

    def __init__(self, name: str, model_info: MotorModelInfo) -> None:
        self._name = name
        self._model_info = model_info
        self._positions: dict[str, Location[float]] = {
            axis: {"setpoint": 0.0, "readback": 0.0} for axis in model_info.axis
        }

        # set the current axis to the first axis
        self.axis = self._model_info.axis[0]

        self._step_sizes = self._model_info.step_sizes

        self.logger.info("Initialized")

    def set(self, value: Any, **kwargs: Any) -> Status:
        """Set something in the mock model.

        Either set the motor position or update a configuration value.
        When setting a configuration value, the keyword argument `prop`
        must be provided.
        Accepted updatable properties:

        - ``axis``: motor axis.
        - ``step_size``: step size for the motor current axis.

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
        s.add_callback(self._update_readback)

        # TODO: this should be "propr" and not "prop";
        # in general though this whole section should be moved
        # to a separate, customized bluesky verb
        propr = kwargs.get("prop", None) or kwargs.get("propr", None)
        if propr is not None:
            self.logger.info("Setting property %s to %s.", propr, value)
            if propr == "axis" and isinstance(value, str):
                self.axis = value
                s.set_finished()
                return s
            elif propr == "step_size" and isinstance(value, int | float):
                self._step_sizes[self.axis] = value
                s.set_finished()
                return s
            else:
                s.set_exception(ValueError(f"Invalid property: {propr}"))
                return s
        else:
            if not isinstance(value, int | float):
                s.set_exception(ValueError("Value must be a float or int."))
                return s
        steps = math.floor(
            (value - self._positions[self.axis]["setpoint"])
            / self._step_sizes[self.axis]
        )
        for _ in range(steps):
            self._positions[self.axis]["setpoint"] += self._step_sizes[self.axis]
        s.set_finished()
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
    def model_info(self) -> MotorModelInfo:  # noqa: D102
        return self._model_info

    def shutdown(self) -> None: ...

    def _update_readback(self, status: Status) -> None:
        """Update the currently active axis readback position.

        When the status object is set as finished successfully,
        the readback position is updated to match the setpoint.

        Parameters
        ----------
        s : Status
            The status object associated with the callback.
        axis : str
            Axis name.
        """
        if status.success:
            self._positions[self.axis]["readback"] = self._positions[self.axis][
                "setpoint"
            ]
