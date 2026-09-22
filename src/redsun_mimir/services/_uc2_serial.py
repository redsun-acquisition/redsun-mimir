"""The wire protocol of a YouSeeToo (UC2) controller.

The board acknowledges a command but reports no position or laser power
back. One port carries every axis and laser, so a command is sent under a
lock, and ``pyserial`` blocks, so a caller keeps these calls off its event
loop.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import msgspec

from ._uc2_actions import Acknowledge, LaserAction, MotorAction, MotorResponse

if TYPE_CHECKING:
    from threading import Lock

    from serial import Serial


#: Nanometres in the micrometre a position is commanded in.
UM_TO_NM: Final[int] = 1_000

#: Nanometres one step of the motor covers.
MOTOR_STEP: Final[int] = 320

#: The stepper each axis is wired to.
AXIS_ID: Final[dict[str, int]] = {"x": 1, "y": 2, "z": 3}


def clean(raw: bytes) -> str:
    """Strip the controller's framing noise out of a response."""
    return (
        str(raw)
        .replace("+", "")
        .replace("-", "")
        .replace("\\r", "")
        .replace("\\n", "")
        .replace("b'", "")
        .replace("'", "")
    )


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
