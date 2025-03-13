from typing import Tuple

import bluesky.plan_stubs as bps
import pytest
from bluesky.protocols import Location
from bluesky.utils import MsgGenerator
from sunflare.engine import RunEngine

from redsun_mimir.model import (
    StageModelInfo,
)
from redsun_mimir.model.openwfs import OWFSStage
from redsun_mimir.protocols import MotorProtocol


def test_motor_construction(motor_openwfs_config: dict[str, StageModelInfo]) -> None:
    """Test the motor object construction."""
    for name, info in motor_openwfs_config.items():
        motor = OWFSStage(name, info)
        assert isinstance(motor, MotorProtocol)
        assert motor.name == name
        assert motor.model_info.axis == info.axis
        assert motor.model_info.egu == info.egu
        assert motor.model_info.step_sizes == info.step_sizes


def test_motor_configurable_protocol(
    motor_openwfs_config: dict[str, StageModelInfo],
) -> None:
    for name, info in motor_openwfs_config.items():
        motor = OWFSStage(name, info)
        cfg = motor.read_configuration()
        assert cfg == {
            "vendor": {"value": "N/A", "timestamp": 0},
            "serial_number": {"value": "N/A", "timestamp": 0},
            "family": {"value": "N/A", "timestamp": 0},
            "axis": {"value": info.axis, "timestamp": 0},
            "step_sizes": {"value": info.step_sizes, "timestamp": 0},
            "egu": {"value": info.egu, "timestamp": 0},
        }


def test_motor_set_direct(motor_openwfs_config: dict[str, StageModelInfo]) -> None:
    """Test the motor movement via direct invocation of the ``set`` method.

    The test moves the motor to position 100 and then to position 200.
    It evaluates that after ``set`` is called, the motor is at the new position,
    the ``Status`` is marked as done and successful, and the ``locate`` method
    returns the new position with the readback value set to the previous position.
    """
    for name, info in motor_openwfs_config.items():
        motor = OWFSStage(name, info)
        # attempting to move a motor along an axis
        # that does not exist should raise an error

        for axis in motor.model_info.axis:
            motor.set(axis, prop="axis")
            status = motor.set(100)
            status.wait()
            assert status.done
            assert status.success
            assert motor.locate() == Location(setpoint=100.0, readback=100.0), (
                "Actual: {}".format(motor.locate())
            )

            status = motor.set(200)
            status.wait()
            assert status.done
            assert status.success
            assert motor.locate() == Location(setpoint=200.0, readback=200.0), (
                "Actual: {}".format(motor.locate())
            )


@pytest.mark.skip(reason="Not implemented yet")
def test_motor_plan_absolute(
    motor_openwfs_config: dict[str, StageModelInfo], RE: RunEngine
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

    motors = tuple(
        [OWFSStage(name, info) for name, info in motor_openwfs_config.items()]
    )
    RE(moving_plan(motors, axis="X"))


@pytest.mark.skip(reason="Not implemented yet")
def test_motor_plan_relative(
    motor_openwfs_config: dict[str, StageModelInfo], RE: RunEngine
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

    motors = tuple(
        [OWFSStage(name, info) for name, info in motor_openwfs_config.items()]
    )
    RE(moving_plan(motors, axis="X"))
