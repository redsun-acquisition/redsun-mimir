from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Event
from typing import TYPE_CHECKING

import numpy as np
from attrs import define, field, setters, validators
from bluesky.protocols import Descriptor
from microscope import ROI, AxisLimits
from microscope.simulators import SimulatedCamera, SimulatedLightSource, SimulatedStage
from sunflare.device import Device
from sunflare.engine import Status
from sunflare.log import Loggable

import redsun_mimir.device.utils as utils
from redsun_mimir.protocols import DetectorProtocol, LightProtocol, MotorProtocol
from redsun_mimir.utils.descriptors import (
    make_array_descriptor,
    make_integer_descriptor,
    make_key,
    make_number_descriptor,
    make_reading,
    make_string_descriptor,
)

if TYPE_CHECKING:
    from concurrent.futures import Future
    from typing import Any, ClassVar

    import numpy.typing as npt
    from bluesky.protocols import Descriptor, Location, Reading


class Factory:
    stage: ClassVar[SimulatedStageDevice | None]
    light: ClassVar[SimulatedLightDevice | None]
    pool: ClassVar[ThreadPoolExecutor]
    stage_ready: ClassVar[Event] = Event()
    light_ready: ClassVar[Event] = Event()

    @classmethod
    def fetch_devices(
        cls,
    ) -> Future[tuple[SimulatedLightDevice, SimulatedStageDevice]]:
        def do_fetch() -> tuple[SimulatedLightDevice, SimulatedStageDevice]:
            cls.stage_ready.wait()
            cls.light_ready.wait()
            assert cls.light is not None and cls.stage is not None
            return cls.light, cls.stage

        cls.pool = ThreadPoolExecutor(1)
        future = cls.pool.submit(do_fetch)
        return future

    @classmethod
    def set_stage(cls, stage: SimulatedStageDevice) -> None:
        cls.stage = stage
        cls.stage_ready.set()

    @classmethod
    def set_light(cls, light: SimulatedLightDevice) -> None:
        cls.light = light
        cls.light_ready.set()


@define(kw_only=True, init=False, eq=False)
class SimulatedStageDevice(Device, MotorProtocol, SimulatedStage, Loggable):  # type: ignore[misc]
    """Simulated stage device using the microscope library.

    Parameters
    ----------
    name : str
        Name of the device.
    egu : str
        Engineering units. Default is "mm".
    axis : list[str]
        Axis names.
    step_sizes : dict[str, float]
        Step sizes for each axis.
    limits : dict[str, tuple[float, float]]
        Position limits for each axis. Required for simulated stages.
    """

    name: str
    prefix: str = field(
        default="SIM",
        validator=validators.instance_of(str),
        metadata={"description": "Device class prefix for key generation."},
    )
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


    def __init__(self, name: str, /, **kwargs: Any) -> None:
        super().__init__(name, **kwargs)
        self.__attrs_init__(name=name, **kwargs)

        if self.limits is None:
            raise ValueError(f"{self.__class__.__name__} requires limits to be set.")

        axis_limits = {
            ax: AxisLimits(lower=lim[0], upper=lim[1])
            for ax, lim in self.limits.items()
        }
        SimulatedStage.__init__(self, axis_limits)
        self._active_axis = self.axis[0]
        Factory.set_stage(self)

    def describe_configuration(self) -> dict[str, Descriptor]:
        descriptors: dict[str, Descriptor] = {
            make_key(self.prefix, self.name, "egu"): make_string_descriptor("settings"),
            make_key(self.prefix, self.name, "axis"): make_array_descriptor(
                "settings", shape=[len(self.axis)]
            ),
        }
        for ax in self.axis:
            key = make_key(self.prefix, self.name, rf"step_size\{ax}")
            if self.limits is not None and ax in self.limits:
                low, high = self.limits[ax]
                descriptors[key] = make_number_descriptor(
                    "settings", low=low, high=high
                )
            else:
                descriptors[key] = make_number_descriptor("settings")
        return descriptors

    def read_configuration(self) -> dict[str, Reading[Any]]:
        timestamp = time.time()
        config: dict[str, Reading[Any]] = {
            make_key(self.prefix, self.name, "egu"): make_reading(self.egu, timestamp),
            make_key(self.prefix, self.name, "axis"): make_reading(self.axis, timestamp),
        }
        for ax, step in self.step_sizes.items():
            config[make_key(self.prefix, self.name, rf"step_size\{ax}")] = (
                make_reading(step, timestamp)
            )
        return config

    def set(self, value: Any, **kwargs: Any) -> Status:
        s = Status()

        propr = kwargs.get("prop", None)
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
        step_size = self.step_sizes[self._active_axis]
        new_position = step_size * np.round(value / step_size)
        self.move_to({self._active_axis: new_position})
        s.set_finished()
        return s

    def locate(self) -> Location[float]:
        return {
            "setpoint": self.position[self._active_axis],
            "readback": self.position[self._active_axis],
        }


@define(kw_only=True, init=False, eq=False)
class SimulatedLightDevice(Device, LightProtocol, SimulatedLightSource, Loggable):  # type: ignore[misc]
    """Simulated light source using the microscope library.

    Parameters
    ----------
    name : str
        Name of the device.
    binary : bool
        Binary mode operation. Not supported for simulated lights.
    wavelength : int
        Wavelength in nm.
    egu : str
        Engineering units. Default is "mW".
    intensity_range : tuple[int | float, ...]
        Intensity range (min, max).
    step_size : int
        Step size for the intensity.
    """

    name: str
    prefix: str = field(
        default="SIM",
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


    def __init__(self, name: str, /, **kwargs: Any) -> None:
        super().__init__(name, **kwargs)
        self.__attrs_init__(name=name, **kwargs)

        if self.binary:
            raise AttributeError(
                f"{self.__class__.__name__} does not support binary light sources."
            )
        if self.intensity_range == (0, 0) or self.intensity_range == (0.0, 0.0):
            raise AttributeError(
                f"{self.__class__.__name__} requires intensity range to be set."
            )
        SimulatedLightSource.__init__(self)
        Factory.set_light(self)

    def describe(self) -> dict[str, Descriptor]:
        return {
            "intensity": {
                "source": self.name,
                "dtype": "number",
                "shape": [],
                "units": self.egu,
                "limits": {
                    "control": {
                        "low": self.intensity_range[0],
                        "high": self.intensity_range[1],
                    }
                },
            },
            "enabled": {
                "source": self.name,
                "dtype": "boolean",
                "shape": [],
            },
        }

    def read(self) -> dict[str, Reading[Any]]:
        return {
            "intensity": {
                "value": self.intensity,
                "timestamp": time.time(),
            },
            "enabled": {
                "value": self.get_is_on(),
                "timestamp": time.time(),
            },
        }

    def describe_configuration(self) -> dict[str, Descriptor]:
        return {
            make_key(self.prefix, self.name, "wavelength"): make_integer_descriptor(
                "settings", units="nm"
            ),
            make_key(self.prefix, self.name, "binary"): make_string_descriptor(
                "settings"
            ),
            make_key(self.prefix, self.name, "egu"): make_string_descriptor("settings"),
            make_key(self.prefix, self.name, "intensity_range"): make_array_descriptor(
                "settings", shape=[2]
            ),
            make_key(self.prefix, self.name, "step_size"): make_integer_descriptor(
                "settings"
            ),
        }

    def read_configuration(self) -> dict[str, Reading[Any]]:
        timestamp = time.time()
        return {
            make_key(self.prefix, self.name, "wavelength"): make_reading(
                self.wavelength, timestamp
            ),
            make_key(self.prefix, self.name, "binary"): make_reading(
                self.binary, timestamp
            ),
            make_key(self.prefix, self.name, "egu"): make_reading(self.egu, timestamp),
            make_key(self.prefix, self.name, "intensity_range"): make_reading(
                list(self.intensity_range), timestamp
            ),
            make_key(self.prefix, self.name, "step_size"): make_reading(
                self.step_size, timestamp
            ),
        }

    def trigger(self) -> Status:
        s = Status()
        self.enable() if not self.get_is_on() else self.disable()
        self.logger.debug(
            f"Toggled light source {not self.get_is_on()} -> {self.get_is_on()}"
        )
        s.set_finished()
        return s

    def set(self, value: Any, **kwargs: Any) -> Status:
        s = Status()
        propr = kwargs.get("prop", None)
        if propr is not None:
            err_msg = f"{self.__class__.__name__} does not support property setting."
            self.logger.error(err_msg)
            s.set_exception(RuntimeError(err_msg))
            return s
        else:
            if not isinstance(value, int | float):
                s.set_exception(ValueError("Value must be a float or int."))
                return s
        self.intensity = value

        # the actual power is set as a percentage of the intensity range
        self.power = (value - self.intensity_range[0]) / (
            self.intensity_range[1] - self.intensity_range[0]
        )
        s.set_finished()
        return s


@define(kw_only=True, init=False, eq=False)
class SimulatedCameraDevice(Device, DetectorProtocol, SimulatedCamera, Loggable):  # type: ignore[misc]
    """Simulated camera model implementing DetectorProtocol.

    Parameters
    ----------
    name : str
        Name of the detector model.
    sensor_shape : tuple[int, int]
        Shape of the sensor (width, height).
    """

    name: str
    prefix: str = field(
        default="SIM",
        validator=validators.instance_of(str),
        metadata={"description": "Device class prefix for key generation."},
    )
    sensor_shape: tuple[int, int] = field(
        default=(512, 512),
        converter=utils.convert_shape,
        metadata={"description": "Shape of the sensor (width, height)."},
    )


    def __init__(self, name: str, /, **kwargs: Any) -> None:
        super().__init__(name, **kwargs)
        self.__attrs_init__(name=name, **kwargs)

        # Initialize SimulatedCamera explicitly with the sensor shape
        SimulatedCamera.__init__(self, sensor_shape=self.sensor_shape)
        self.initialize()

        # Set initial ROI to full sensor
        self.roi = (0, 0, *self.sensor_shape)

        self._queue: Queue[tuple[npt.NDArray[Any], float]] = Queue()
        self.set_client(self._queue)
        # Key names for data collection
        self._buffer_key = f"{self.name}:buffer"
        self._roi_key = f"{self.name}:roi"

    def describe_configuration(self) -> dict[str, Descriptor]:
        """Describe the detector configuration."""
        config: dict[str, Descriptor] = {}
        for setting_name in self.get_all_settings():
            config[make_key(self.prefix, self.name, setting_name)] = (
                make_string_descriptor("settings")
            )
        config[make_key(self.prefix, self.name, "sensor_shape")] = (
            make_array_descriptor("settings", shape=[2])
        )
        return config

    def read_configuration(self) -> dict[str, Reading[Any]]:
        """Read the detector configuration."""
        timestamp = time.time()
        config: dict[str, Reading[Any]] = {}
        for setting_name, setting_value in self.get_all_settings().items():
            config[make_key(self.prefix, self.name, setting_name)] = make_reading(
                setting_value, timestamp
            )
        config[make_key(self.prefix, self.name, "sensor_shape")] = make_reading(
            list(self.sensor_shape), timestamp
        )
        return config

    def set(self, value: Any, **kwargs: Any) -> Status:
        """Set detector parameters.

        This method uses the SimulatedCamera's set_setting method to configure
        camera parameters based on the get_all_settings structure.

        Parameters
        ----------
        value : Any
            The value to set.
        **kwargs
            Additional keyword arguments including 'prop' for property name.

        Returns
        -------
        Status
            Status object indicating success or failure.
        """
        s = Status()

        try:
            prop = kwargs.get("prop", None)
            if prop is not None:
                # Use the SimulatedCamera's setting mechanism
                if prop in self.get_all_settings():
                    self.set_setting(prop, value)
                    self.logger.debug(f"Set {prop} to {value} for {self.name}")
                else:
                    raise ValueError(f"Unknown property: {prop}")
            else:
                # Handle ROI setting if no specific property is given
                if isinstance(value, tuple) and len(value) == 4:
                    self.roi = value
                    # Convert tuple to ROI object: (x, y, width, height)
                    roi_obj = ROI(
                        left=value[0], top=value[1], width=value[2], height=value[3]
                    )
                    self.set_roi(roi_obj)
                    self.logger.debug(f"Set ROI to {value} for {self.name}")
                else:
                    raise ValueError(
                        "Value must specify a property via 'prop' keyword or be a 4-tuple for ROI"
                    )

            s.set_finished()
        except Exception as e:
            self.logger.error(
                f"Failed to set {kwargs.get('prop', 'ROI')} to {value}: {e}"
            )
            s.set_exception(e)

        return s

    def stage(self) -> Status:
        """Prepare the detector for acquisition."""
        s = Status()
        try:
            self.enable()
            self._do_enable()
            self.logger.debug(f"Staged {self.name}")
            s.set_finished()
        except Exception as e:
            self.logger.error(f"Failed to stage {self.name}: {e}")
            s.set_exception(e)
        return s

    def unstage(self) -> Status:
        """Stop the detector acquisition."""
        s = Status()
        try:
            self.disable()
            self.logger.debug(f"Unstaged {self.name}")
            s.set_finished()
        except Exception as e:
            self.logger.error(f"Failed to unstage {self.name}: {e}")
            s.set_exception(e)
        return s

    def kickoff(self) -> Status:
        """Kick off a continuous acquisition."""
        s = Status()
        try:
            # Start acquisition mode
            self.logger.debug(f"Kicked off acquisition for {self.name}")
            s.set_finished()
        except Exception as e:
            self.logger.error(f"Failed to kickoff {self.name}: {e}")
            s.set_exception(e)
        return s

    def complete(self) -> Status:
        """Complete a continuous acquisition."""
        s = Status()
        try:
            self.logger.debug(f"Completed acquisition for {self.name}")
            s.set_finished()
        except Exception as e:
            self.logger.error(f"Failed to complete {self.name}: {e}")
            s.set_exception(e)
        return s

    def trigger(self) -> Status:
        """Trigger the detector to acquire an image."""
        s = Status()
        try:
            super().trigger()
            s.set_finished()
        except Exception as e:
            self.logger.error(f"Failed to trigger {self.name}: {e}")
            s.set_exception(e)
        return s

    def describe(
        self,
    ) -> dict[str, Descriptor]:
        """Describe the a reading from a detector."""
        ret_val: dict[str, Descriptor] = {
            self._buffer_key: {
                "source": self.name,
                "dtype": "array",
                "shape": list(self.sensor_shape),
            },
            self._roi_key: {
                "source": self.name,
                "dtype": "array",
                "shape": [4],
            },
        }
        return ret_val

    def read(self) -> dict[str, Reading[Any]]:
        """Read data from the detector.

        Returns
        -------
        dict[str, Reading[Any]]
            A dictionary containing the readings from the detector.
        """
        timestamp: float
        data: npt.NDArray[Any]
        queue_item = self._queue.get()
        if len(queue_item) == 2:
            data, timestamp = queue_item
        else:
            data = queue_item  # type: ignore[unreachable]
            timestamp = time.time()
        return {
            self._buffer_key: {
                "value": data,
                "timestamp": timestamp,
            },
            self._roi_key: {
                "value": self.roi,
                "timestamp": timestamp,
            },
        }
