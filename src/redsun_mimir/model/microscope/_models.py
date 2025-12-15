from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
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
    from collections.abc import Iterator
    from concurrent.futures import Future
    from typing import Any, ClassVar

    from bluesky.protocols import Descriptor, Location, Reading
    from event_model.documents.event import PartialEvent

    from redsun_mimir.model import DetectorModelInfo, LightModelInfo, MotorModelInfo


class Factory:
    stage: ClassVar[SimulatedStageModel | None]
    light: ClassVar[SimulatedLightModel | None]
    pool: ClassVar[ThreadPoolExecutor]
    stage_ready: ClassVar[Event] = Event()
    light_ready: ClassVar[Event] = Event()

    @classmethod
    def fetch_devices(
        cls,
    ) -> Future[tuple[SimulatedLightModel, SimulatedStageModel]]:
        def do_fetch() -> tuple[SimulatedLightModel, SimulatedStageModel]:
            cls.stage_ready.wait()
            cls.light_ready.wait()
            assert cls.light is not None and cls.stage is not None
            return cls.light, cls.stage

        cls.pool = ThreadPoolExecutor(1)
        future = cls.pool.submit(do_fetch)
        return future

    @classmethod
    def set_stage(cls, stage: SimulatedStageModel) -> None:
        cls.stage = stage
        cls.stage_ready.set()

    @classmethod
    def set_light(cls, light: SimulatedLightModel) -> None:
        cls.light = light
        cls.light_ready.set()


class SimulatedStageModel(MotorProtocol, SimulatedStage, Loggable):  # type: ignore[misc]
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
        return self.model_info.describe_configuration()

    def read_configuration(self) -> dict[str, Reading[Any]]:
        return self.model_info.read_configuration()

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
        step_size = self.model_info.step_sizes[self.axis]
        new_position = step_size * np.round(value / step_size)
        self.move_to({self.axis: new_position})
        s.set_finished()
        return s

    def locate(self) -> Location[float]:
        return {
            "setpoint": self.position[self.axis],
            "readback": self.position[self.axis],
        }

    @property
    def name(self) -> str:
        return self._name

    @property
    def model_info(self) -> MotorModelInfo:
        return self._model_info

    @property
    def parent(self) -> None:
        return None


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

    def describe_collect(
        self,
    ) -> dict[str, Descriptor] | dict[str, dict[str, Descriptor]]:
        """Describe the data that will be collected."""
        return {
            self._buffer_key: {
                "source": self.name,
                "dtype": "array",
                "shape": list(self.model_info.sensor_shape),
                "external": "FILESTORE:" + self._buffer_key,
            },
            self._roi_key: {
                "source": self.name,
                "dtype": "array",
                "shape": [4],  # ROI is (x, y, width, height)
            },
        }

    def collect(self) -> Iterator[PartialEvent]:
        """Collect data from the detector.

        Yields
        ------
        Iterator[PartialEvent]
            Partial event documents with image data and ROI.
        """
        timestamp = time.time()

        try:
            # Get image data from SimulatedCamera (returns tuple of (image, timestamp))
            image_data, image_timestamp = self.grab_next_data()

            yield {
                "data": {
                    self._buffer_key: image_data,
                    self._roi_key: self.roi,
                },
                "timestamps": {
                    self._buffer_key: image_timestamp,
                    self._roi_key: timestamp,
                },
                "time": timestamp,
            }
        except Exception as e:
            self.logger.error(f"Failed to collect data from {self.name}: {e}")
            raise

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
