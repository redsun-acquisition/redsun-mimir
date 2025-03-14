from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Event
from typing import TYPE_CHECKING

import numpy as np
from bluesky.protocols import Descriptor, Reading
from microscope import AxisLimits
from microscope.simulators import SimulatedCamera, SimulatedLightSource, SimulatedStage
from sunflare.engine import Status
from sunflare.log import Loggable

from redsun_mimir.protocols import DetectorProtocol, LightProtocol, MotorProtocol

if TYPE_CHECKING:
    from concurrent.futures import Future
    from typing import Any, ClassVar, Optional

    import numpy.typing as npt
    from bluesky.protocols import Descriptor, Location, Reading

    from redsun_mimir.model import DetectorModelInfo, LightModelInfo, StageModelInfo


class Factory:
    stage: ClassVar[Optional[SimulatedStageModel]]
    light: ClassVar[Optional[SimulatedLightModel]]
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
            raise ValueError(f"{self.__clsname__} requires limits to be set.")
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
            self.info("Setting property %s to %s.", propr, value)
            if propr == "axis" and isinstance(value, str):
                self.axis = value
                s.set_finished()
                return s
            elif propr == "step_size" and isinstance(value, (int, float)):
                self.model_info.step_sizes[self.axis] = value
                s.set_finished()
                return s
            else:
                s.set_exception(ValueError(f"Invalid property: {propr}"))
                return s
        else:
            if not isinstance(value, (int, float)):
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
                f"{self.__clsname__} does not support binary light sources."
            )
        if model_info.intensity_range == (0, 0):
            raise AttributeError(
                f"{self.__clsname__} requires intensity range to be set."
            )
        self._name = name
        self._model_info = model_info
        SimulatedLightSource.__init__(self)
        Factory.set_light(self)

    def describe_configuration(self) -> dict[str, Descriptor]:
        return self.model_info.describe_configuration()

    def read_configuration(self) -> dict[str, Reading[Any]]:
        return self.model_info.read_configuration()

    def trigger(self) -> Status:
        s = Status()
        self.enable() if not self.get_is_on() else self.disable()
        self.debug(f"Toggled light source {not self.get_is_on()} -> {self.get_is_on()}")
        s.set_finished()
        return s

    def set(self, value: Any, **kwargs: Any) -> Status:
        s = Status()
        propr = kwargs.get("prop", None)
        if propr is not None:
            err_msg = f"{self.__clsname__} does not support property setting."
            self.error(err_msg)
            s.set_exception(RuntimeError(err_msg))
            return s
        else:
            if not isinstance(value, (int, float)):
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


def map_type_descriptor(t: str) -> str:
    type_mapping = {
        "int": "integer",
        "float": "number",
        "bool": "boolean",
        "str": "string",
        "enum": "array",
        "tuple": "array",
    }
    result = type_mapping.get(t, "unknown")
    if result == "unknown":
        raise ValueError(f"Type {t} not recognized.")
    return result


class SimulatedCameraModel(DetectorProtocol, SimulatedCamera, Loggable):  # type: ignore[misc]
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

        self._queue: Queue[tuple[npt.ArrayLike, float]] = Queue()
        self.set_client(self._queue)

    def describe(self) -> dict[str, Descriptor]:
        return {
            self.name: {
                "source": "queue",
                "dtype": "array",
                "shape": [list(self.model_info.sensor_shape)],
            }
        }

    def read(self) -> dict[str, Reading[npt.ArrayLike]]:
        value, timestamp = self._queue.get()
        return {
            "queue": {
                "value": value,
                "timestamp": timestamp,
            }
        }

    def describe_configuration(self) -> dict[str, Descriptor]:
        descriptor = self.model_info.describe_configuration()
        settings = self.describe_settings()
        for setting in settings:
            name, content = setting
            descriptor.update(
                {
                    "source": name,
                    "dtype": map_type_descriptor(content["type"]),
                    "shape": len(content["values"])
                    if content["values"] is not None
                    else [],
                }
            )

        return descriptor

    def read_configuration(self) -> dict[str, Reading[Any]]:
        stamp = time.time()
        reading = self.model_info.read_configuration(stamp)
        settings = self.get_all_settings()
        for name, setting in settings.items():
            reading.update({name: {"value": setting, "timestamp": stamp}})
        return reading

    def shutdown(self) -> None:
        SimulatedCamera.shutdown(self)

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
