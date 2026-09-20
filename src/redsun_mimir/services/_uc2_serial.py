"""The wire protocol of a YouSeeToo (UC2) controller.

The board is write-only over its serial link: it acknowledges a command but
offers no way to read a position or a laser power back. One port carries every
axis and every laser, so a command is sent under a lock, and ``pyserial``
blocks, so a caller keeps these calls off its event loop.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import msgspec

from ._uc2_actions import Acknowledge, LaserAction, MotorAction, MotorResponse

if TYPE_CHECKING:
    from threading import Lock

    from serial import Serial


NM_TO_NM: Final[int] = 1
UM_TO_NM: Final[int] = 1_000
MM_TO_NM: Final[int] = 1_000_000

MOTOR_STEP: Final[int] = 320

AXIS_ID: Final[dict[str, int]] = {"x": 1, "y": 2, "z": 3}
CONVERSION: Final[dict[str, int]] = {
    "nm": NM_TO_NM,
    "um": UM_TO_NM,
    "mm": MM_TO_NM,
}


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
