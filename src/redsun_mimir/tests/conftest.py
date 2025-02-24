from pathlib import Path

import pytest


@pytest.fixture
def motor_config_path() -> str:
    path = Path(__file__).parent / "data" / "test_motor_config.yaml"
    return str(path)
