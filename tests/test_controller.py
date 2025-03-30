import time

from bluesky.protocols import Location
from psygnal import emit_queued
from pytestqt.qtbot import QtBot
from sunflare.controller import ControllerProtocol
from sunflare.virtual import HasConnection, HasRegistration, VirtualBus

from redsun_mimir.controller import (
    LightController,
    LightControllerInfo,
    StageController,
    StageControllerInfo,
)
from redsun_mimir.model import (
    LightModelInfo,
    MockLightModel,
    MockStageModel,
    StageModelInfo,
)


def test_stage_controller(
    bus: VirtualBus, motor_config: dict[str, StageModelInfo], qtbot: QtBot
) -> None:
    motors = {name: MockStageModel(name, info) for name, info in motor_config.items()}

    info = StageControllerInfo(plugin_name="test", plugin_id="test")
    ctrl = StageController(info, motors, bus)

    assert isinstance(ctrl, ControllerProtocol | HasRegistration | HasConnection)

    def check_new_position(motor: str, position: float) -> None:
        assert motor == "Mock motor"
        assert position == 100

    def check_new_parameters(motor: str, success: dict[str, bool]) -> None:
        name = list(success.keys())[0]
        axis = success[name]

        assert motor == "Mock motor"
        assert name == "axis"
        assert axis

    with qtbot.waitSignals([ctrl.sigNewPosition, ctrl.sigNewConfiguration]):
        ctrl._do_move(motors["Mock motor"], "X", 100)
        ctrl.sigNewPosition.connect(check_new_position)
        ctrl.sigNewConfiguration.connect(check_new_parameters)
        assert ctrl._motors["Mock motor"].locate() == Location(
            readback=100, setpoint=100
        )
        ctrl.configure("Mock motor", {"axis": "Y"})

    ctrl.sigNewConfiguration.disconnect(check_new_parameters)
    ctrl.sigNewPosition.disconnect(check_new_position)

    with qtbot.waitSignal(ctrl.sigNewPosition):
        ctrl.sigNewPosition.connect(check_new_position, thread="main")
        ctrl.move("Mock motor", "X", 100)
        # give time to the callback to be invoked...
        # best approach would be to probably
        # hack "move" to set an event
        time.sleep(0.3)
        emit_queued()
        assert ctrl._motors["Mock motor"].locate() == Location(
            readback=100, setpoint=100
        )

    ctrl.shutdown()

    assert not ctrl._daemon.is_alive()


def test_light_widget(
    bus: VirtualBus, light_config: dict[str, LightModelInfo], qtbot: QtBot
) -> None:
    lights = {name: MockLightModel(name, info) for name, info in light_config.items()}

    info = LightControllerInfo(plugin_name="test", plugin_id="test")
    ctrl = LightController(info, lights, bus)

    assert isinstance(ctrl, ControllerProtocol | HasRegistration | HasConnection)
    assert not ctrl._lights["Mock laser"].enabled
    ctrl.trigger("Mock laser")
    assert ctrl._lights["Mock laser"].enabled

    # mypy complains that the statement
    # is unreachable; not sure why;
    # we just ignore this
    ctrl.set("Mock laser", 0.5)  # type: ignore
    assert ctrl._lights["Mock laser"].intensity == 0.5
