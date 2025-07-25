from pathlib import Path
from typing import Any

import pytest
import yaml

from redsun_mimir.model import LightModelInfo, MotorModelInfo


def test_mock_motor_model_info(config_path: Path) -> None:
    """Test the MockStageModel information model."""
    config: MotorModelInfo

    motor_config_path = str(config_path / "test_motor_config.yaml")

    with open(motor_config_path) as file:
        config_dict: dict[str, Any] = yaml.safe_load(file)
        for _, values in config_dict["models"].items():
            config = MotorModelInfo(**values)

    assert config.axis == ["X", "Y", "Z"]
    assert config.step_sizes == {"X": 100.0, "Y": 100.0, "Z": 100.0}
    assert config.egu == "um"


def test_mock_light_model_info(config_path: Path) -> None:
    container: list[LightModelInfo] = []

    light_config_path = str(config_path / "test_light_config.yaml")
    with open(light_config_path) as file:
        config_dict: dict[str, Any] = yaml.safe_load(file)
        for _, values in config_dict["models"].items():
            container.append(LightModelInfo(**values))

    config = tuple(container)

    laser, led, microscope = config

    assert laser.intensity_range == (0.0, 100.0)
    assert laser.egu == "mW"
    assert not laser.binary

    assert led.intensity_range == (0.0, 0.0)
    assert led.egu == "mW"
    assert led.binary

    assert microscope.intensity_range == (0.0, 100.0)
    assert microscope.egu == "mW"
    assert not microscope.binary


def test_broken_light_model_info(config_path: Path) -> None:
    """Test the broken light model information."""
    light_config_path = str(config_path / "test_incorrect_light_config.yaml")

    with open(light_config_path) as file:
        config_dict: dict[str, Any] = yaml.safe_load(file)
        for _, values in config_dict["models"].items():
            with pytest.raises(AttributeError):
                LightModelInfo(**values)
