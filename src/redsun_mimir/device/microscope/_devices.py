from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Event
from typing import TYPE_CHECKING

import numpy as np
from bluesky.protocols import Descriptor
from microscope import ROI, AxisLimits
from microscope.simulators import SimulatedCamera, SimulatedLightSource, SimulatedStage
from sunflare.engine import Status
from sunflare.log import Loggable

from redsun_mimir.protocols import DetectorProtocol, LightProtocol, MotorProtocol

if TYPE_CHECKING:
    from concurrent.futures import Future
    from typing import Any, ClassVar

    import numpy.typing as npt
    from bluesky.protocols import Descriptor, Location, Reading

    from redsun_mimir.device import DetectorModelInfo, LightModelInfo, MotorModelInfo


class Factory:
    stage: ClassVar[SimulatedStageDevice | None]
    light: ClassVar[SimulatedLightModel | None]
    pool: ClassVar[ThreadPoolExecutor]
    stage_ready: ClassVar[Event] = Event()
    light_ready: ClassVar[Event] = Event()

    @classmethod
    def fetch_devices(
        cls,
    ) -> Future[tuple[SimulatedLightModel, SimulatedStageDevice]]:
        def do_fetch() -> tuple[SimulatedLightModel, SimulatedStageDevice]:
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
    def set_light(cls, light: SimulatedLightModel) -> None:
        cls.light = light
        cls.light_ready.set()


class SimulatedStageDevice(MotorProtocol, SimulatedStage, Loggable):  # type: ignore[misc]
    def __init__(self, name: str, model_info: MotorModelInfo) -> None:
        self._name = name
        self._model_info = model_info
        if model_info.limits is None:
            raise ValueError(f"{self.__class__.__name__} requires limits to be set.")
        limits = {
            axis: AxisLimits(
                lower=limit[0],
                upper=limit[1],
            )
            for axis, limit in model_info.limits.items()
        }
        super().__init__(limits)
        self.axis = model_info.axis[0]
        Factory.set_stage(self)

    def describe_configuration(self) -> dict[str, Descriptor]:
        return {}

    def read_configuration(self) -> dict[str, Reading[Any]]:
        return {}

    def set(self, value: Any, **kwargs: Any) -> Status:
        s = Status()

        propr = kwargs.get("prop", None)
        if propr is not None:
            self.logger.info("Setting property %s to %s.", propr, value)
            if propr == "axis" and isinstance(value, str):
                self.axis = value
                s.set_finished()
                return s
            elif propr == "step_size" and isinstance(value, int | float):
                self.model_info.step_sizes[self.axis] = value
                s.set_finished()
                return s
            else:
                s.set_exception(ValueError(f"Invalid property: {propr}"))
                return s
        else:
            if not isinstance(value, int | float):
                s.set_exception(ValueError("Value must be a float or int."))
                return s
        step_size = self.step_sizes[self.axis]
        new_position = step_size * np.round(value / step_size)
        self.move_to({self.axis: new_position})
        s.set_finished()
        return s

    def locate(self) -> Location[float]:
        return {
            "setpoint": self.position[self.axis],
            "readback": self.position[self.axis],
        }


class SimulatedLightModel(LightProtocol, SimulatedLightSource, Loggable):  # type: ignore[misc]
    def __init__(self, name: str, model_info: LightModelInfo) -> None:
        if model_info.binary:
            raise AttributeError(
                f"{self.__class__.__name__} does not support binary light sources."
            )
        if model_info.intensity_range == (0, 0):
            raise AttributeError(
                f"{self.__class__.__name__} requires intensity range to be set."
            )
        self._name = name
        self._model_info = model_info
        super().__init__()
        Factory.set_light(self)

    def describe(self) -> dict[str, Descriptor]:
        return {
            "intensity": {
                "source": self.name,
                "dtype": "number",
                "shape": [],
                "units": self.model_info.egu,
                "limits": {
                    "control": {
                        "low": self.model_info.intensity_range[0],
                        "high": self.model_info.intensity_range[1],
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
        return self.model_info.describe_configuration()

    def read_configuration(self) -> dict[str, Reading[Any]]:
        return self.model_info.read_configuration()

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
        self.power = (value - self.model_info.intensity_range[0]) / (
            self.model_info.intensity_range[1] - self.model_info.intensity_range[0]
        )
        s.set_finished()
        return s

    @property
    def name(self) -> str:
        return self._name

    @property
    def model_info(self) -> LightModelInfo:
        return self._model_info

    @property
    def parent(self) -> None:
        return None


class SimulatedCameraModel(DetectorProtocol, SimulatedCamera, Loggable):  # type: ignore[misc]
    """Simulated camera model implementing DetectorProtocol.

    This class provides a complete detector interface by inheriting from:
    - DetectorProtocol: Bluesky detector interface
    - SimulatedCamera: Microscope library camera simulator
    - Loggable: Logging capabilities

    Parameters
    ----------
    name : str
        Name of the detector model.
    model_info : DetectorModelInfo
        Configuration information for the detector.
    """

    def __init__(self, name: str, model_info: DetectorModelInfo) -> None:
        self._name = name
        self._model_info = model_info

        # Initialize SimulatedCamera explicitly with the sensor shape from model_info
        SimulatedCamera.__init__(self, sensor_shape=model_info.sensor_shape)
        self.initialize()

        # Set initial ROI to full sensor
        self.roi = (0, 0, *model_info.sensor_shape)

        self._queue: Queue[tuple[npt.NDArray[Any], float]] = Queue()
        self.set_client(self._queue)
        # Key names for data collection
        self._buffer_key = f"{self.name}:buffer"
        self._roi_key = f"{self.name}:roi"

    def describe_configuration(self) -> dict[str, Descriptor]:
        """Describe the detector configuration."""
        return self.model_info.describe_configuration()

    def read_configuration(self) -> dict[str, Reading[Any]]:
        """Read the detector configuration."""
        timestamp = time.time()
        config = self.model_info.read_configuration(timestamp)

        # Add current camera settings to configuration
        settings = self.get_all_settings()
        for setting_name, setting_value in settings.items():
            config[f"{self.name}:{setting_name}"] = {
                "value": setting_value,
                "timestamp": timestamp,
            }

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
                "shape": list(self.model_info.sensor_shape),
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

    @property
    def name(self) -> str:
        """Name of the detector."""
        return self._name

    @property
    def model_info(self) -> DetectorModelInfo:
        """Configuration information for the detector."""
        return self._model_info

    @property
    def parent(self) -> None:
        """Parent device (None for top-level devices)."""
        return None
