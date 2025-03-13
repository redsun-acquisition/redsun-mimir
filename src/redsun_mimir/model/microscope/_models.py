from __future__ import annotations

from typing import TYPE_CHECKING

from microscope import AxisLimits
from microscope.simulators import SimulatedStage
from sunflare.engine import Status
from sunflare.log import Loggable

from redsun_mimir.protocols import MotorProtocol

if TYPE_CHECKING:
    from typing import Any

    from bluesky.protocols import Descriptor, Location, Reading

    from redsun_mimir.model import StageModelInfo


class MicroscopeStageModel(MotorProtocol, SimulatedStage, Loggable):  # type: ignore[misc]
    def __init__(self, name: str, model_info: StageModelInfo) -> None:
        self._name = name
        self._model_info = model_info
        if model_info.limits is None:
            raise ValueError("The limits of the model must be defined.")
        limits = {
            axis: AxisLimits(
                lower=limit[0],
                upper=limit[1],
            )
            for axis, limit in model_info.limits.items()
        }
        SimulatedStage.__init__(self, limits)
        self.axis = model_info.axis[0]

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
        self.move_to({self.axis: value + self.model_info.step_sizes[self.axis]})
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
