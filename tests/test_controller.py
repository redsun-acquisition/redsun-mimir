from redsun_mimir.controller import StageController
from redsun_mimir.config import StageControllerInfo, StageModelInfo
from redsun_mimir.model import MockStageModel

from sunflare.virtual import VirtualBus

def test_stage_controller(bus: VirtualBus, motor_config: dict[str, StageModelInfo]) -> None:

    motors = {
        name: MockStageModel(name, info)
        for name, info in motor_config.items()
    }

    info = StageControllerInfo()
    ctrl = StageController(info, motors, bus)

    assert ctrl._motors == motors
