from pathlib import Path
from typing import Any

from pytestqt.qtbot import QtBot
from sunflare.config import RedSunSessionInfo
from sunflare.virtual import VirtualBus

from redsun_mimir.controller import MotorControllerInfo
from redsun_mimir.model import MotorModelInfo
from redsun_mimir.widget import MotorWidget


def test_stage_widget(config_path: Path, qtbot: QtBot, bus: VirtualBus) -> None:
    motor_config_path = str(config_path / "test_motor_config.yaml")

    config_dict = RedSunSessionInfo.load_yaml(str(motor_config_path))
    config_dict["models"] = {
        k: MotorModelInfo(**v) for k, v in config_dict["models"].items()
    }
    config_dict["controllers"] = {
        k: MotorControllerInfo(**v) for k, v in config_dict["controllers"].items()
    }
    config_dict["views"] = {}

    config = RedSunSessionInfo(**config_dict)

    assert config.models["Mock motor"] == config_dict["models"]["Mock motor"]
    assert config.engine == config_dict["engine"]
    assert config.frontend == config_dict["frontend"]
    assert (
        config.controllers["MotorController"]
        == config_dict["controllers"]["MotorController"]
    )
    assert config.views == {}

    widget = MotorWidget(config, bus)
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
        expected_value = -100.0
        widget._buttons[f"button:{motor_id}:{expected_axis}:down"].click()

    widget.sigMotorMove.disconnect(assert_move_signal)

    def assert_config_signal(name: str, config: dict[str, Any]) -> None:
        nonlocal motor_id
        nonlocal expected_axis
        nonlocal expected_value
        axis = list(config.keys())[0]
        value = config[axis]

        assert name == motor_id
        assert axis == expected_axis
        assert isinstance(value, float)
        assert value == expected_value

    with qtbot.waitSignal(widget.sigConfigChanged):
        widget.sigConfigChanged.connect(assert_config_signal)
        expected_value = 200.0
        widget._line_edits[f"edit:{motor_id}:{expected_axis}"].setText("200.0")
        widget._line_edits[f"edit:{motor_id}:{expected_axis}"].editingFinished.emit()

    with qtbot.assertNotEmitted(widget.sigConfigChanged):
        widget._line_edits[f"edit:{motor_id}:{expected_axis}"].setText("aaa")
        widget._line_edits[f"edit:{motor_id}:{expected_axis}"].editingFinished.emit()
        assert widget._line_edits[f"edit:{motor_id}:{expected_axis}"].text() == "aaa"
        assert (
            widget._line_edits[f"edit:{motor_id}:{expected_axis}"].styleSheet()
            == "border: 2px solid red;"
        )
