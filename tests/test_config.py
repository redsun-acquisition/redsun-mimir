import yaml
from pathlib import Path
from typing import Any

from redsun_mimir import StageModelInfo


def test_mock_motor_model_info(config_path: Path) -> None:
    """Test the MockStageModel information model."""

    config: StageModelInfo

    motor_config_path = str(config_path / "test_motor_config.yml")

    with open(motor_config_path, "r") as file:
        config_dict: dict[str, Any] = yaml.safe_load(file)
        for _, values in config_dict["models"].items():
            config = StageModelInfo(**values)

    assert config.model_name == "MockStageModel"
    assert config.axis == ["X", "Y", "Z"]
    assert config.step_sizes == {"X": 100.0, "Y": 100.0, "Z": 100.0}
    assert config.egu == "um"
