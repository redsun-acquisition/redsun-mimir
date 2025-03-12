from pathlib import Path
from typing import Any, Tuple

import bluesky.plan_stubs as bps
import pytest
import yaml
from bluesky.protocols import Location, Reading
from bluesky.utils import MsgGenerator
from sunflare.engine import RunEngine

from redsun_mimir.model import (
    LightModelInfo,
    MockLightModel,
    MockStageModel,
    StageModelInfo,
)
from redsun_mimir.protocols import LightProtocol, MotorProtocol


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
def RE() -> RunEngine:
    """Return a ``RunEngine`` instance."""
    return RunEngine()


def test_motor_construction(motor_config: dict[str, StageModelInfo]) -> None:
    """Test the motor object construction."""
    for name, info in motor_config.items():
        motor = MockStageModel(name, info)
        assert isinstance(motor, MotorProtocol)
        assert motor.name == name
        assert motor.model_info.axis == info.axis
        assert motor.model_info.egu == info.egu
        assert motor.model_info.step_sizes == info.step_sizes


def test_motor_configurable_protocol(motor_config: dict[str, StageModelInfo]) -> None:
    for name, info in motor_config.items():
        motor = MockStageModel(name, info)
        cfg = motor.read_configuration()
        assert cfg == {
            "vendor": {"value": "N/A", "timestamp": 0},
            "serial_number": {"value": "N/A", "timestamp": 0},
            "family": {"value": "N/A", "timestamp": 0},
            "axis": {"value": info.axis, "timestamp": 0},
            "step_sizes": {"value": info.step_sizes, "timestamp": 0},
            "egu": {"value": info.egu, "timestamp": 0},
        }


def test_motor_set_direct(motor_config: dict[str, StageModelInfo]) -> None:
    """Test the motor movement via direct invocation of the ``set`` method.

    The test moves the motor to position 100 and then to position 200.
    It evaluates that after ``set`` is called, the motor is at the new position,
    the ``Status`` is marked as done and successful, and the ``locate`` method
    returns the new position with the readback value set to the previous position.
    """
    for name, info in motor_config.items():
        motor = MockStageModel(name, info)
        # attempting to move a motor along an axis
        # that does not exist should raise an error

        for axis in motor.model_info.axis:
            motor.set(axis, prop="axis")
            status = motor.set(100)
            status.wait()
            assert status.done
            assert status.success
            assert motor.locate() == Location(setpoint=100.0, readback=100.0)

            status = motor.set(200)
            status.wait()
            assert status.done
            assert status.success
            assert motor.locate() == Location(setpoint=200.0, readback=200.0)


def test_motor_plan_absolute(
    motor_config: dict[str, StageModelInfo], RE: RunEngine
) -> None:
    """Test motor execution in a ``RunEngine`` plan.

    Motors will move based on absolute positions.

    - first move to position 100;
    - then move to position 200.
    """

    def moving_plan(motors: Tuple[MotorProtocol, ...], axis: str) -> MsgGenerator[None]:
        """Move the motor to position 100 and then to position 200."""
        for m in motors:
            yield from bps.abs_set(m, axis, prop="axis")
            yield from bps.mv(m, 100)
            yield from bps.mv(m, 200)
            location = yield from bps.locate(m)  # type: ignore
            assert location == Location(setpoint=200.0, readback=200.0)

    motors = tuple([MockStageModel(name, info) for name, info in motor_config.items()])
    RE(moving_plan(motors, axis="X"))


def test_motor_plan_relative(
    motor_config: dict[str, StageModelInfo], RE: RunEngine
) -> None:
    """Test motor execution in a ``RunEngine`` plan.

    Motors will move based on relative positions.

    - first move of 100;
    - then move of 200.
    """

    def moving_plan(motors: Tuple[MotorProtocol, ...], axis: str) -> MsgGenerator[None]:
        """Move the motor of 100 steps and then of 200 steps."""
        for m in motors:
            yield from bps.abs_set(m, axis, prop="axis")
            yield from bps.mvr(m, 100)
            yield from bps.mvr(m, 200)
            location = yield from bps.locate(m)  # type: ignore
            assert location == Location(setpoint=300.0, readback=300.0)

    motors = tuple([MockStageModel(name, info) for name, info in motor_config.items()])
    RE(moving_plan(motors, axis="X"))


def test_light_construction(light_config: dict[str, LightModelInfo]) -> None:
    """Test the motor object construction."""
    for name, info in light_config.items():
        motor = MockLightModel(name, info)
        assert isinstance(motor, LightProtocol)
        assert motor.name == name
        assert motor.model_info.intensity_range == info.intensity_range
        assert motor.model_info.egu == info.egu


def test_light_configurable_protocol(light_config: dict[str, LightModelInfo]) -> None:
    for name, info in light_config.items():
        light = MockLightModel(name, info)
        cfg = light.read_configuration()
        assert cfg == {
            "vendor": {"value": "N/A", "timestamp": 0},
            "serial_number": {"value": "N/A", "timestamp": 0},
            "family": {"value": "N/A", "timestamp": 0},
            "intensity_range": {"value": info.intensity_range, "timestamp": 0},
            "egu": {"value": info.egu, "timestamp": 0},
            "wavelength": {"value": info.wavelength, "timestamp": 0},
            "step_size": {"value": info.step_size, "timestamp": 0},
            "binary": {"value": info.binary, "timestamp": 0},
        }


def test_light_set_direct(light_config: dict[str, LightModelInfo]) -> None:
    for name, info in light_config.items():
        light = MockLightModel(name, info)
        # attempting to move a motor along an axis
        # that does not exist should raise an error

        s = light.set(100)
        s.wait()
        assert s.done and s.success
        assert light.read() == {
            "intensity": Reading(value=100.0, timestamp=0),
            "enabled": Reading(value=False, timestamp=0),
        }
        with pytest.raises(ValueError):
            light.set("test")


def test_light_plan(light_config: dict[str, LightModelInfo], RE: RunEngine) -> None:
    def setting_plan(lights: Tuple[LightProtocol, ...]) -> MsgGenerator[None]:
        """Move the motor of 100 steps and then of 200 steps."""
        for L in lights:
            yield from bps.trigger(L)
            yield from bps.abs_set(L, 100)
            reading = yield from bps.read(L)
            assert reading == Reading(value=100.0, timestamp=0)

    lights = tuple([MockLightModel(name, info) for name, info in light_config.items()])
    RE(setting_plan(lights))
