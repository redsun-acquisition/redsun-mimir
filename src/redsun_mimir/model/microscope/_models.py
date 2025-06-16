from __future__ import annotations

import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Event
from typing import TYPE_CHECKING

import numpy as np
from bluesky.protocols import Descriptor, Reading
from microscope import ROI as mROI
from microscope import AxisLimits
from microscope.simulators import SimulatedCamera, SimulatedLightSource, SimulatedStage
from sunflare.engine import Status
from sunflare.log import Loggable

from redsun_mimir.protocols import ROI, DetectorProtocol, LightProtocol, MotorProtocol

if TYPE_CHECKING:
    from concurrent.futures import Future
    from typing import Any, ClassVar

    import numpy.typing as npt
    from bluesky.protocols import Descriptor, Location, Reading

    from redsun_mimir.model import DetectorModelInfo, LightModelInfo, StageModelInfo


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
    def __init__(self, name: str, model_info: StageModelInfo) -> None:
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
        SimulatedStage.__init__(self, limits)
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
    def model_info(self) -> StageModelInfo:
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
        SimulatedLightSource.__init__(self)
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
    _pattern_map = {
        "noise": 0,
        "gradient": 1,
        "sawtooth": 2,
        "one_gaussian": 3,
        "black": 4,
        "white": 5,
    }

    _dtype_map = {
        "uint8": 0,
        "uint16": 1,
        "float": 2,
    }

    def __init__(
        self,
        name: str,
        model_info: DetectorModelInfo,
    ):
        self._name = name
        self._model_info = model_info

        # TODO: implement _fetch
        # to adjust field of view
        # self.future = Factory.fetch_devices()
        # self._light: SimulatedLightModel
        # self._stage: SimulatedStageModel

        # def set_devices(
        #     future: Future[tuple[SimulatedLightModel, SimulatedStageModel]],
        # ) -> None:
        #     self._light, self._stage = future.result()

        # self.future.add_done_callback(set_devices)

        SimulatedCamera.__init__(self, sensor_shape=model_info.sensor_shape)
        self.set_setting("image pattern", self._pattern_map["noise"])
        self.set_setting("image data type", self._dtype_map["uint8"])

        self._queue: Queue[tuple[npt.ArrayLike, float]] = Queue()
        self.roi = ROI(0, 0, *model_info.sensor_shape)
        self.set_roi(mROI(*self.roi))
        self.set_client(self._queue)

    def set(self, value: Any, **kwargs: Any) -> Status:
        """Set a configuration parameter.

        i.e.

        .. code-block:: python

            status = camera.set(0.1, propr="exposure")
        """
        s = Status()
        propr = kwargs.get("propr", None)
        if propr is not None:
            if propr not in [
                "exposure",
                "image pattern",
                "image data type",
                "gain",
                "display image number",
                "roi",
            ]:
                s.set_exception(ValueError(f"Invalid property: {propr}"))
                return s
            else:
                exception: Exception | None = None
                match propr:
                    case "exposure":
                        if not isinstance(value, (int, float)):
                            exception = ValueError(
                                "Exposure time must be a float or int."
                            )
                        self.set_exposure_time(float(value))
                    case "image pattern":
                        if self.get_setting(propr) != self._pattern_map[value]:
                            exception = ValueError(
                                f"Invalid image pattern: {value}. "
                                f"Valid patterns are: {list(self._pattern_map.keys())}."
                            )
                        self.set_setting(propr, self._pattern_map[value])
                    case "image data type":
                        if not isinstance(value, str) or value not in self._dtype_map:
                            exception = ValueError(
                                f"Invalid image data type: {value}. "
                                f"Valid types are: {list(self._dtype_map.keys())}."
                            )
                        self.set_setting(propr, self._dtype_map[value])
                    case "gain":
                        if not isinstance(value, (int, float)):
                            exception = ValueError("Gain must be a float or int.")
                        self.set_setting(propr, float(value))
                    case "display image number":
                        if not isinstance(value, bool):
                            exception = ValueError(
                                "Display image number must be a boolean."
                            )
                        self.set_setting(propr, value)
                    case "roi":
                        if isinstance(value, Sequence) and len(value) == 4:
                            new_roi = ROI(*value)
                            exception = ValueError(
                                "ROI must be a tuple of (x, y, width, height)."
                            )
                            if not (
                                0 <= new_roi.x < self.model_info.sensor_shape[1]
                                and 0 <= new_roi.y < self.model_info.sensor_shape[0]
                                and new_roi.x + new_roi.width
                                <= self.model_info.sensor_shape[1]
                                and new_roi.y + new_roi.height
                                <= self.model_info.sensor_shape[0]
                            ):
                                exception = ValueError(
                                    "ROI must be within the sensor shape bounds."
                                )
                        else:
                            exception = ValueError(
                                "ROI must be a sequence of four numbers (x, y, width, height)."
                            )
                        if self.set_roi(mROI(*value)):
                            self.roi = ROI(*value)
                        else:
                            exception = ValueError(
                                "Failed to set ROI. Ensure the values are within the sensor shape bounds."
                            )
                if exception:
                    s.set_exception(exception)
                    return s
                self.logger.debug("Set %s to %s.", propr, value)
                s.set_finished()
                return s

        if not isinstance(value, int | float):
            s.set_exception(ValueError("Value must be a float or int."))
            return s
        self.set_exposure_time(float(value))
        s.set_finished()
        return s

    def describe(self) -> dict[str, Descriptor]:
        return {
            "queue": {
                "source": self.name,
                "dtype": "array",
                "shape": list(self.model_info.sensor_shape),
            }
        }

    def read(self) -> dict[str, Reading[npt.ArrayLike]]:
        content = self._queue.get()
        try:
            value, timestamp = content
        except Exception:
            value = content[0]
            timestamp = time.time()
        return {
            "queue": {
                "value": value,
                "timestamp": timestamp,
            }
        }

    def describe_configuration(self) -> dict[str, Descriptor]:
        descriptor = self.model_info.describe_configuration("model_info/readonly")
        settings = self.describe_settings()
        for setting in settings:
            name, content = setting
            if name in ["image pattern", "image data type"]:
                descriptor.update(
                    {
                        name: {
                            "source": "settings",
                            "dtype": "string",
                            "choices": [choice[-1] for choice in content["values"]],
                            "shape": [len(content["values"])],
                        }
                    }
                )
            if name == "display image number":
                descriptor.update(
                    {
                        name: {
                            "source": "settings",
                            "dtype": "boolean",
                            "shape": [],
                        }
                    }
                )
            if name == "gain":
                descriptor.update(
                    {
                        name: {
                            "source": "settings",
                            "dtype": "number",
                            "shape": [],
                            "units": "dB",
                            "limits": {
                                "control": {
                                    "low": content["values"][0],
                                    "high": content["values"][1],
                                }
                            },
                        }
                    }
                )

        descriptor.update(
            {
                "exposure": {
                    "source": "timings",
                    "dtype": "number",
                    "shape": [],
                    "units": "ms",
                    "limits": {
                        "control": {
                            "low": 1,
                            "high": 1000,
                        }
                    },
                }
            }
        )
        return descriptor

    def read_configuration(self) -> dict[str, Reading[Any]]:
        reading = self.model_info.read_configuration()
        settings = self.get_all_settings()
        timestamp = time.time()
        for name, setting in settings.items():
            if name in [
                "image pattern",
                "image data type",
                "display image number",
                "gain",
            ]:
                if name == "image pattern":
                    # extract the pattern name from the current setting value
                    setting = list(self._pattern_map.keys())[setting]
                if name == "image data type":
                    # extract the data type from the current setting value
                    setting = list(self._dtype_map.keys())[setting]
                reading.update(
                    {
                        name: {
                            "value": setting,
                            "timestamp": timestamp,
                        }
                    }
                )
        reading.update(
            {
                "exposure": {"value": self.get_exposure_time(), "timestamp": timestamp},
            }
        )

        return reading

    def shutdown(self) -> None:
        SimulatedCamera.shutdown()

    def trigger(self) -> Status:
        SimulatedCamera.trigger()
        s = Status()
        s.set_finished()
        return s

    def stage(self) -> Status:
        s = Status()
        try:
            self.enable()
        except Exception as e:
            s.set_exception(e)
        else:
            s.set_finished()
        return s

    def unstage(self) -> Status:
        s = Status()
        try:
            self.disable()
        except Exception as e:
            s.set_exception(e)
        else:
            s.set_finished()
        return s

    @property
    def name(self) -> str:
        return self._name

    @property
    def model_info(self) -> DetectorModelInfo:
        return self._model_info

    @property
    def parent(self) -> None:
        return None
