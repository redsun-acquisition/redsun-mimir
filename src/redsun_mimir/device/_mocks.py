from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING

from attrs import define, field, setters, validators
from redsun.device import Device
from redsun.engine import Status
from redsun.log import Loggable

import redsun_mimir.device.utils as utils
from redsun_mimir.protocols import LightProtocol, MotorProtocol
from redsun_mimir.utils.descriptors import (
    make_descriptor,
    make_key,
    make_reading,
    parse_key,
)

if TYPE_CHECKING:
    from typing import Any

    from bluesky.protocols import Descriptor, Location, Reading


@define(kw_only=True, init=False, eq=False)
class MockLightDevice(Device, LightProtocol, Loggable):
    """Mock light source for simulation and testing purposes."""

    name: str
    prefix: str = field(
        default="MOCK",
        validator=validators.instance_of(str),
        metadata={"description": "Device class prefix for key generation."},
    )
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
        if not self.binary and value[0] == value[1]:
            raise AttributeError(
                f"Non-binary device must have a non-degenerate intensity range "
                f"(min != max), got: {value}"
            )

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
        timestamp = time.time()
        return {
            make_key(self.name, "wavelength"): make_reading(self.wavelength, timestamp),
            make_key(self.name, "binary"): make_reading(self.binary, timestamp),
            make_key(self.name, "egu"): make_reading(self.egu, timestamp),
            make_key(self.name, "intensity_range"): make_reading(
                list(self.intensity_range), timestamp
            ),
            make_key(self.name, "step_size"): make_reading(self.step_size, timestamp),
        }

    def describe_configuration(self) -> dict[str, Descriptor]:
        return {
            make_key(self.name, "wavelength"): make_descriptor(
                "settings", "integer", units="nm", readonly=True
            ),
            make_key(self.name, "binary"): make_descriptor(
                "settings", "string", readonly=True
            ),
            make_key(self.name, "egu"): make_descriptor(
                "settings", "string", readonly=True
            ),
            make_key(self.name, "intensity_range"): make_descriptor(
                "settings", "array", shape=[2], readonly=True
            ),
            make_key(self.name, "step_size"): make_descriptor("settings", "integer"),
        }

    def shutdown(self) -> None: ...

    def trigger(self) -> Status:
        """Toggle the activation status of the light source."""
        self.enabled = not self.enabled
        s = Status()
        s.set_finished()
        return s


@define(kw_only=True, init=False, eq=False)
class MockMotorDevice(Device, MotorProtocol, Loggable):
    """Mock stage model for testing purposes.

    Parameters
    ----------
    name : ``str``
        Name of the device.
    prefix : ``str``, optional
        Prefix for key generation. Default is "MOCK".
    egu : ``str``, optional
        Engineering units for the motor position. Default is "mm".
    axis : ``list[str]``
        List of motor axes. No default value, must be provided.
    step_sizes : ``dict[str, float]``, optional
        Dictionary mapping each axis to its step size. Default is an empty dictionary.
    limits : ``dict[str, tuple[float, float]]``, optional
        Dictionary mapping each axis to a tuple of (min, max) limits. Default is ``None`` (no limits).
    """

    name: str
    prefix: str = field(default="MOCK", validator=validators.instance_of(str))
    egu: str = field(
        default="mm", validator=validators.instance_of(str), on_setattr=setters.frozen
    )
    axis: list[str] = field(
        validator=validators.instance_of(list), on_setattr=setters.frozen
    )
    step_sizes: dict[str, float] = field(validator=validators.instance_of(dict))
    limits: dict[str, tuple[float, float]] | None = field(
        default=None, converter=utils.convert_limits, validator=utils.check_limits
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

        self._descriptors: dict[str, Descriptor] = {
            make_key(self.name, "egu"): make_descriptor(
                "settings", "string", readonly=True
            ),
            make_key(self.name, "axis"): make_descriptor(
                "settings", "array", shape=[len(self.axis)], readonly=True
            ),
        }
        for ax in self.axis:
            key = make_key(self.name, rf"{ax}_step_size")
            if self.limits is not None and ax in self.limits:
                low, high = self.limits[ax]
                self._descriptors[key] = make_descriptor(
                    "settings", "number", low=low, high=high
                )
            else:
                self._descriptors[key] = make_descriptor("settings", "number")

        self._active_axis = self.axis[0]
        self.logger.info("Initialized")

    def set(self, value: Any, **kwargs: Any) -> Status:
        r"""Set something in the mock model.

        Either set the motor position or update a configuration value.
        When setting a configuration value, the keyword argument ``propr``
        must be provided as a canonical ``prefix:name\property`` key.
        For backwards compatibility, a bare name via ``prop`` is also accepted.

        Accepted updatable properties:

        - ``axis``: motor axis.
        - ``step_size``: step size for the currently active axis (bare form).
        - ``{ax}_step_size``: step size for a specific axis (e.g. ``"X_step_size"``).

        i.e. ``set(10)`` will set the motor position to 10,
        ``set("Y", propr="MOCK:stage-axis")`` will update the axis to "Y",
        ``set(0.5, propr="MOCK:stage-X_step_size")`` updates the X step size.

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

        raw = kwargs.get("propr", None) or kwargs.get("prop", None)
        if raw is not None:
            # Accept either a canonical key ("prefix:name-property") or a bare name
            try:
                _, propr = parse_key(str(raw))
            except ValueError:
                propr = str(raw)
            self.logger.info("Setting property %s to %s.", propr, value)
            if propr == "axis" and isinstance(value, str):
                self._active_axis = value
                s.set_finished()
                return s
            elif propr == "step_size" and isinstance(value, int | float):
                # bare "step_size" updates the currently active axis
                self.step_sizes[self._active_axis] = value
                s.set_finished()
                return s
            elif propr.endswith("_step_size") and isinstance(value, int | float):
                # axis-qualified form: "{ax}_step_size" (e.g. "X_step_size")
                ax = propr[: -len("_step_size")]
                if ax in self.step_sizes:
                    self.step_sizes[ax] = value
                    s.set_finished()
                    return s
                s.set_exception(ValueError(f"Unknown axis in property: {propr}"))
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
        timestamp = time.time()
        config: dict[str, Reading[Any]] = {
            make_key(self.name, "egu"): make_reading(self.egu, timestamp),
            make_key(self.name, "axis"): make_reading(self.axis, timestamp),
        }
        for ax, step in self.step_sizes.items():
            config[make_key(self.name, f"{ax}_step_size")] = make_reading(
                step, timestamp
            )
        return config

    def describe_configuration(self) -> dict[str, Descriptor]:
        return self._descriptors

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
