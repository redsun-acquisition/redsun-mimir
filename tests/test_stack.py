import time
from pathlib import Path

from psygnal import emit_queued
from pytestqt.qtbot import QtBot
from sunflare.config import RedSunSessionInfo
from sunflare.virtual import VirtualBus

from redsun_mimir import (
    MockStageModel,
    StageController,
    StageControllerInfo,
    StageModelInfo,
    StageWidget,
)


def test_stage_stack(config_path: Path, qtbot: QtBot, bus: VirtualBus) -> None:
    motor_config_path = str(config_path / "test_motor_config.yaml")

    config_dict = RedSunSessionInfo.load_yaml(str(motor_config_path))
    config_dict["models"] = {k: StageModelInfo(**v) for k, v in config_dict["models"].items()}
    config_dict["controllers"] = {k: StageControllerInfo(**v) for k, v in config_dict["controllers"].items()}
    config_dict["widgets"] = {}

    config = RedSunSessionInfo(**config_dict)

    motors = {name: MockStageModel(name, info) for name, info in config.models.items()} # type: ignore

    ctrl = StageController(config.controllers["StageController"], motors, bus) # type: ignore
    widget = StageWidget(config, bus)

    ctrl.registration_phase()
    widget.registration_phase()
    ctrl.connection_phase()
    widget.connection_phase()

    qtbot.addWidget(widget)

    expected_axis = "X"
    motor_id = "Mock motor"
    expected_value = 0.0

    def assert_move_signal(motor_name: str, motor_axis: str, position: float) -> None:
        nonlocal expected_value
        nonlocal motor_id
        nonlocal expected_axis
        assert motor_name == motor_id
        assert motor_axis == expected_axis
        assert position == expected_value

    with qtbot.waitSignal(widget.sigMotorMove):
        widget.sigMotorMove.connect(assert_move_signal)
        expected_value = 100.0
        widget._buttons[f"button:{motor_id}:{expected_axis}:up"].click()
        time.sleep(0.1)
        emit_queued()
        expected_value = 0
        widget._buttons[f"button:{motor_id}:{expected_axis}:down"].click()
        time.sleep(0.1)
        emit_queued()
        for _ in range(2):
            expected_value += 100.0
            widget._buttons[f"button:{motor_id}:{expected_axis}:up"].click()
            time.sleep(0.1)
            emit_queued()

