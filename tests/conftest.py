from pathlib import Path
from typing import Any, Generator

import pytest
import yaml
from sunflare.engine import RunEngine
from sunflare.virtual import VirtualBus

from redsun_mimir.model import LightModelInfo, StageModelInfo


@pytest.fixture
def config_path() -> Path:
    return Path(__file__).parent / "data"


@pytest.fixture(scope="function")
def RE() -> RunEngine:
    """Return a ``RunEngine`` instance."""
    return RunEngine()


@pytest.fixture(scope="function")
def bus() -> Generator[VirtualBus, None, None]:
    yield VirtualBus()


@pytest.fixture
def motor_config(config_path: Path) -> dict[str, StageModelInfo]:
    """Return the motors configuration."""
    motors: dict[str, StageModelInfo] = {}

    motor_config_path = str(config_path / "test_motor_config.yaml")

    with open(motor_config_path, "r") as file:
        config_dict: dict[str, Any] = yaml.safe_load(file)
        for name, values in config_dict["models"].items():
            config = StageModelInfo(**values)
            motors[name] = config
    return motors


@pytest.fixture
def light_config(config_path: Path) -> dict[str, LightModelInfo]:
    """Return the light configuration."""
    lights: dict[str, LightModelInfo] = {}

    light_config_path = str(config_path / "test_light_config.yaml")

    with open(light_config_path, "r") as file:
        config_dict: dict[str, Any] = yaml.safe_load(file)
        for name, values in config_dict["models"].items():
            config = LightModelInfo(**values)
            lights[name] = config
    return lights


@pytest.fixture
def motor_openwfs_config(config_path: Path) -> dict[str, StageModelInfo]:
    """Return the motors configuration."""
    motors: dict[str, StageModelInfo] = {}

    motor_config_path = str(config_path / "test_openwfs_motor.yaml")

    with open(motor_config_path, "r") as file:
        config_dict: dict[str, Any] = yaml.safe_load(file)
        for name, values in config_dict["models"].items():
            config = StageModelInfo(**values)
            motors[name] = config
    return motors


@pytest.fixture
def light_openwfs_config(config_path: Path) -> dict[str, LightModelInfo]:
    """Return the light configuration."""
    lights: dict[str, LightModelInfo] = {}

    light_config_path = str(config_path / "test_openwfs_light.yaml")

    with open(light_config_path, "r") as file:
        config_dict: dict[str, Any] = yaml.safe_load(file)
        for name, values in config_dict["models"].items():
            config = LightModelInfo(**values)
            lights[name] = config
    return lights
