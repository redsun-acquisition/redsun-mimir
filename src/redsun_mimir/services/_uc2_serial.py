"""The wire protocol of a YouSeeToo (UC2) controller.

The board acknowledges a command, answers a query for where its steppers
stand, and reports no laser power back. One port carries every axis and
laser, so a command is sent under a lock, and ``pyserial`` blocks, so a
caller keeps these calls off its event loop.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import msgspec

from ._uc2_actions import (
    Acknowledge,
    LaserAction,
    MotorAction,
    MotorResponse,
    MotorStateResponse,
)

if TYPE_CHECKING:
    from threading import Lock

    from serial import Serial


#: Nanometres in the micrometre a position is commanded in.
UM_TO_NM: Final[int] = 1_000

#: Nanometres one step of the motor covers.
MOTOR_STEP: Final[int] = 320

#: The stepper each axis is wired to.
AXIS_ID: Final[dict[str, int]] = {"x": 1, "y": 2, "z": 3}

#: What the board answers with the state of every stepper it carries.
POSITION_QUERY: Final[bytes] = b'{"task":"/motor_get"}'


def clean(raw: bytes) -> str:
    """Return the document in *raw*, without the board's framing.

    The board wraps an answer in ``++`` and ``--`` and breaks it over lines.
    Cutting at the outermost braces keeps the minus sign of a negative
    position, which stripping the framing characters would take with it.
    """
    text = raw.decode(errors="ignore")
    opened, closed = text.find("{"), text.rfind("}")
    return text[opened : closed + 1] if 0 <= opened < closed else ""


def read_positions(serial: Serial, lock: Lock, factor: int) -> dict[int, float]:
    """Ask the board where its steppers stand, keyed by stepper id.

    *factor* is the nanometres in the unit a position is wanted in, as
    `move_axis` takes it; `AXIS_ID` names the id of each axis.
    """
    with lock:
        serial.reset_input_buffer()
        written = serial.write(POSITION_QUERY)
        if written is None or written != len(POSITION_QUERY):
            raise RuntimeError("Failed to write to serial port.")

        answer = clean(serial.read_until(expected=b"--"))
        if not answer:
            raise RuntimeError("Failed to read from serial port.")
        try:
            response = msgspec.json.decode(answer, type=MotorStateResponse)
        except msgspec.DecodeError as e:
            raise RuntimeError(f"Failed to decode stepper state: {e}") from e
        return {
            stepper.id: stepper.position * MOTOR_STEP / factor
            for stepper in response.motor.steppers
        }


def move_axis(
    serial: Serial, lock: Lock, axis_id: int, factor: int, value: float
) -> None:
    """Command one axis to *value* and consume both acknowledgements."""
    with lock:
        serial.reset_input_buffer()
        steps = int(value * factor / MOTOR_STEP)
        action = MotorAction(
            movement=MotorAction.generate_movement(id=axis_id, position=steps),
            qid=axis_id,
        )
        packet = msgspec.json.encode(action)
        written = serial.write(packet)
        if written is None or written != len(packet):
            raise RuntimeError("Failed to write to serial port.")

        resp_str = clean(serial.read_until(expected=b"--"))
        if not resp_str:
            raise RuntimeError("Failed to read from serial port.")
        try:
            response = msgspec.json.decode(resp_str, type=Acknowledge)
        except msgspec.DecodeError as e:
            raise RuntimeError(f"Failed to decode response: {e}") from e
        if response.qid != axis_id:
            raise RuntimeError(f"Invalid response from motor. Received: {response}")

        motor_resp_str = clean(serial.read_until(expected=b"--"))
        if not motor_resp_str:
            raise RuntimeError("Failed to read motor response from serial port.")
        try:
            motor_response = msgspec.json.decode(motor_resp_str, type=MotorResponse)
        except msgspec.DecodeError as e:
            raise RuntimeError(f"Failed to decode motor response: {e}") from e
        if motor_response.qid != axis_id:
            raise RuntimeError(
                f"Invalid response from motor. Expected qid {axis_id}, "
                f"but received {motor_response.qid}."
            )


def set_laser(serial: Serial, lock: Lock, laser_id: int, qid: int, value: int) -> None:
    """Command a laser to *value* and consume its acknowledgement."""
    with lock:
        serial.reset_input_buffer()
        action = LaserAction(id=laser_id, qid=qid, value=value)
        packet = msgspec.json.encode(action)
        written = serial.write(packet)
        if written is None or written != len(packet):
            raise RuntimeError("Failed to write to serial port.")

        resp_str = clean(serial.read_until(expected=b"}"))
        if not resp_str:
            raise RuntimeError("Failed to read from serial port.")
        response = msgspec.json.decode(resp_str, type=Acknowledge)
        if response.qid != qid:
            raise RuntimeError(f"Invalid response from laser. Received: {response}")
