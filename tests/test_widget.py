from pathlib import Path

from pytestqt.qtbot import QtBot
from sunflare.config import RedSunSessionInfo
from sunflare.virtual import VirtualBus

from redsun_mimir import StageModelInfo, StageWidget


def test_stage_widget(config_path: Path, qtbot: QtBot, bus: VirtualBus) -> None:

    motor_config_path = str(config_path / "test_motor_config.yaml")

    config_dict = RedSunSessionInfo.load_yaml(str(motor_config_path))
    models_info = {
        k: StageModelInfo(**v) for k, v in config_dict["models"].items()
    }
    config_dict.update(models=models_info)
    config_dict["controllers"] = {}
    config_dict["widgets"] = {}

    config = RedSunSessionInfo(**config_dict)

    assert config.models["Mock motor"] == config_dict["models"]["Mock motor"]
    assert config.engine == config_dict["engine"]
    assert config.frontend == config_dict["frontend"]
    assert config.controllers == {}
    assert config.widgets == {}

    expected_axis = "X"
    motor_id = "Mock motor"

    widget = StageWidget(config, bus)
    qtbot.addWidget(widget)

    expected_position: float

    def assert_move_signal(motor_name: str, motor_axis: str, position: float) -> None:
        nonlocal expected_position
        nonlocal motor_id
        nonlocal expected_axis
        assert motor_name == motor_id
        assert motor_axis == expected_axis
        assert position == expected_position

    with qtbot.waitSignal(widget.sigMotorMove):
        widget.sigMotorMove.connect(assert_move_signal)
        expected_position = 100.0
        widget._buttons[f"button:{motor_id}:{expected_axis}:up"].click()
        expected_position = -100.0
        widget._buttons[f"button:{motor_id}:{expected_axis}:down"].click()