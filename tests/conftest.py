from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
import yaml
from sunflare.engine import RunEngine
from sunflare.virtual import VirtualBus

from redsun_mimir.device import DetectorModelInfo, LightModelInfo, MotorModelInfo


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
def motor_config(config_path: Path) -> dict[str, MotorModelInfo]:
    """Return the motors configuration."""
    motors: dict[str, MotorModelInfo] = {}

    motor_config_path = str(config_path / "test_motor_config.yaml")

    with open(motor_config_path) as file:
        config_dict: dict[str, Any] = yaml.safe_load(file)
        for name, values in config_dict["models"].items():
            config = MotorModelInfo(**values)
            motors[name] = config
    return motors


@pytest.fixture
def light_config(config_path: Path) -> dict[str, LightModelInfo]:
    """Return the light configuration."""
    lights: dict[str, LightModelInfo] = {}

    light_config_path = str(config_path / "test_light_config.yaml")

    with open(light_config_path) as file:
        config_dict: dict[str, Any] = yaml.safe_load(file)
        for name, values in config_dict["models"].items():
            config = LightModelInfo(**values)
            lights[name] = config
    return lights


@pytest.fixture
def detector_config(config_path: Path) -> dict[str, DetectorModelInfo]:
    """Return the detector configuration."""
    detectors: dict[str, DetectorModelInfo] = {}

    detector_config_path = str(config_path / "test_detector_config.yaml")

    with open(detector_config_path) as file:
        config_dict: dict[str, Any] = yaml.safe_load(file)
        for name, values in config_dict["models"].items():
            config = DetectorModelInfo(**values)
            detectors[name] = config
    return detectors
