from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import TYPE_CHECKING

import numpy as np
from bluesky.protocols import Descriptor, Reading
from microscope import AxisLimits
from microscope.simulators import SimulatedLightSource, SimulatedStage
from sunflare.engine import Status
from sunflare.log import Loggable

from redsun_mimir.protocols import LightProtocol, MotorProtocol

if TYPE_CHECKING:
    from concurrent.futures import Future
    from typing import Any, ClassVar

    from bluesky.protocols import Descriptor, Location, Reading

    from redsun_mimir.model import LightModelInfo, MotorModelInfo


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
