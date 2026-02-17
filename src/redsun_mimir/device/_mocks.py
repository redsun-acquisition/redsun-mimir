from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING

from attrs import define, field, setters, validators
from sunflare.device import Device
from sunflare.engine import Status
from sunflare.log import Loggable

import redsun_mimir.device.utils as utils
from redsun_mimir.protocols import LightProtocol, MotorProtocol

if TYPE_CHECKING:
    from typing import Any

    from bluesky.protocols import Descriptor, Location, Reading


@define(kw_only=True, init=False)
class MockLightDevice(Device, LightProtocol, Loggable):
    """Mock light source for simulation and testing purposes."""

    name: str
    binary: bool = field(
        default=False,
        validator=validators.instance_of(bool),
        metadata={"description": "Binary mode operation."},
    )
    wavelength: int = field(
        default=0,
        validator=validators.instance_of(int),
        metadata={"description": "Wavelength in nm."},
    )
    egu: str = field(
        default="mW",
        validator=validators.instance_of(str),
        on_setattr=setters.frozen,
        metadata={"description": "Engineering units."},
    )
    intensity_range: tuple[int | float, ...] = field(
        default=None,
        converter=utils.convert_to_tuple,
        metadata={"description": "Intensity range (min, max)."},
    )
    step_size: int = field(
        default=1,
        validator=validators.instance_of(int),
        metadata={"description": "Step size for the intensity."},
    )

    @intensity_range.validator
    def _check_range(self, _: str, value: tuple[int | float, ...]) -> None:
        if self.binary and value == (0.0, 0.0):
            return
        if len(value) != 2:
            raise AttributeError(
                f"Length of intensity range must be 2: {value} has length {len(value)}"
            )
        if not all(isinstance(val, (float, int)) for val in value):
            raise AttributeError(
                f"All values in the intensity range must be floats or ints: {value}"
            )
        if value[0] > value[1]:
            raise AttributeError(f"Min value is greater than max value: {value}")

    def __init__(self, name: str, /, **kwargs: Any) -> None:
        super().__init__(name, **kwargs)
        self.__attrs_init__(name=name, **kwargs)
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
        return {}

    def describe_configuration(self) -> dict[str, Descriptor]:
        return {}

    def shutdown(self) -> None: ...

    def trigger(self) -> Status:
        """Toggle the activation status of the light source."""
        self.enabled = not self.enabled
        s = Status()
        s.set_finished()
        return s


@define(kw_only=True, init=False)
class MockMotorDevice(Device, MotorProtocol, Loggable):
    """Mock stage model for testing purposes."""

    name: str
    egu: str = field(
        default="mm",
        validator=validators.instance_of(str),
        on_setattr=setters.frozen,
        metadata={"description": "Engineering units."},
    )
    axis: list[str] = field(
        validator=validators.instance_of(list),
        on_setattr=setters.frozen,
        metadata={"description": "Axis names."},
    )
    step_sizes: dict[str, float] = field(
        validator=validators.instance_of(dict),
        metadata={"description": "Step sizes for each axis."},
    )
    limits: dict[str, tuple[float, float]] | None = field(
        default=None,
        converter=utils.convert_limits,
        metadata={"description": "Limits for each axis."},
    )

    @limits.validator
    def _check_limits(
        self, _: str, value: dict[str, tuple[float, float]] | None
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

    def __init__(self, name: str, /, **kwargs: Any) -> None:
        super().__init__(name, **kwargs)
        self.__attrs_init__(name=name, **kwargs)
        self._positions: dict[str, Location[float]] = {
            axis: {"setpoint": 0.0, "readback": 0.0} for axis in self.axis
        }

        self._active_axis = self.axis[0]

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
                self._active_axis = value
                s.set_finished()
                return s
            elif propr == "step_size" and isinstance(value, int | float):
                self.step_sizes[self._active_axis] = value
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
            (value - self._positions[self._active_axis]["setpoint"])
            / self.step_sizes[self._active_axis]
        )
        for _ in range(steps):
            self._positions[self._active_axis]["setpoint"] += self.step_sizes[
                self._active_axis
            ]
        s.set_finished()
        return s

    def locate(self) -> Location[float]:
        """Locate mock model."""
        return self._positions[self._active_axis]

    def read_configuration(self) -> dict[str, Reading[Any]]:
        """Read mock configuration."""
        return {}

    def describe_configuration(self) -> dict[str, Descriptor]:
        """Describe mock configuration."""
        return {}

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
            self._positions[self._active_axis]["readback"] = self._positions[
                self._active_axis
            ]["setpoint"]
