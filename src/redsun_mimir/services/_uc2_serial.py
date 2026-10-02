"""The wire protocol of a YouSeeToo (UC2) controller.

The board acknowledges a command, answers a query for where its steppers
stand, and reports no laser power back. One port carries every axis and
laser, so a command and its answers are exchanged under a lock. The port's
reads and writes are awaited, so none of this blocks the event loop.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Protocol

import msgspec

from ._uc2_actions import (
    Acknowledge,
    LaserAction,
    MotorAction,
    MotorResponse,
    MotorStateResponse,
)

if TYPE_CHECKING:
    from asyncio import Lock
    from collections.abc import Awaitable


#: Nanometres in the micrometre a position is commanded in.
UM_TO_NM: Final[int] = 1_000

#: Nanometres one step of the motor covers.
NM_PER_STEP: Final[int] = 320

#: The stepper each axis is wired to.
AXIS_ID: Final[dict[str, int]] = {"x": 1, "y": 2, "z": 3}

#: What the board answers with the state of every stepper it carries.
POSITION_QUERY: Final[bytes] = b'{"task":"/motor_get"}'


class SerialPort(Protocol):
    """What the protocol needs of a port: `oxiserial.aio.Serial` is one."""

    @property
    def is_open(self) -> bool:
        """Whether the port is open."""
        ...

    def reset_input_buffer(self) -> None:
        """Discard what the port has received and not read."""
        ...

    def write(self, data: bytes) -> Awaitable[int]:
        """Send *data*, answering how many bytes went out."""
        ...

    def read_until(self, expected: bytes) -> Awaitable[bytes]:
        """Read until *expected* or the port's timeout."""
        ...

    def close(self) -> None:
        """Close the port."""
        ...


def extract_json(raw: bytes) -> str:
    """Return the document in *raw*, without the board's framing.

    The board wraps an answer in ``++`` and ``--`` and breaks it over lines.
    Cutting at the outermost braces keeps the minus sign of a negative
    position, which stripping the framing characters would take with it.
    """
    text = raw.decode(errors="ignore")
    opened, closed = text.find("{"), text.rfind("}")
    return text[opened : closed + 1] if 0 <= opened < closed else ""


async def read_positions(
    serial: SerialPort, lock: Lock, nm_per_unit: int
) -> dict[int, float]:
    """Ask the board where its steppers stand, keyed by stepper id.

    *nm_per_unit* is the nanometres in the unit a position is wanted in, as
    `move_axis` takes it; `AXIS_ID` names the id of each axis.
    """
    async with lock:
        serial.reset_input_buffer()
        written = await serial.write(POSITION_QUERY)
        if written != len(POSITION_QUERY):
            raise RuntimeError("Failed to write to serial port.")

        answer = extract_json(await serial.read_until(expected=b"--"))
        if not answer:
            raise RuntimeError("Failed to read from serial port.")
        try:
            response = msgspec.json.decode(answer, type=MotorStateResponse)
        except msgspec.DecodeError as e:
            raise RuntimeError(f"Failed to decode stepper state: {e}") from e
        return {
            stepper.id: stepper.position * NM_PER_STEP / nm_per_unit
            for stepper in response.motor.steppers
        }


async def move_axis(
    serial: SerialPort, lock: Lock, axis_id: int, nm_per_unit: int, value: float
) -> None:
    """Command one axis to *value* and consume both acknowledgements."""
    async with lock:
        serial.reset_input_buffer()
        steps = int(value * nm_per_unit / NM_PER_STEP)
        action = MotorAction(
            movement=MotorAction.generate_movement(id=axis_id, position=steps),
            qid=axis_id,
        )
        packet = msgspec.json.encode(action)
        written = await serial.write(packet)
        if written != len(packet):
            raise RuntimeError("Failed to write to serial port.")

        resp_str = extract_json(await serial.read_until(expected=b"--"))
        if not resp_str:
            raise RuntimeError("Failed to read from serial port.")
        try:
            response = msgspec.json.decode(resp_str, type=Acknowledge)
        except msgspec.DecodeError as e:
            raise RuntimeError(f"Failed to decode response: {e}") from e
        if response.qid != axis_id:
            raise RuntimeError(f"Invalid response from motor. Received: {response}")

        motor_resp_str = extract_json(await serial.read_until(expected=b"--"))
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


async def set_laser(
    serial: SerialPort, lock: Lock, laser_id: int, qid: int, value: int
) -> None:
    """Command a laser to *value* and consume its acknowledgement."""
    async with lock:
        serial.reset_input_buffer()
        action = LaserAction(id=laser_id, qid=qid, value=value)
        packet = msgspec.json.encode(action)
        written = await serial.write(packet)
        if written != len(packet):
            raise RuntimeError("Failed to write to serial port.")

        resp_str = extract_json(await serial.read_until(expected=b"}"))
        if not resp_str:
            raise RuntimeError("Failed to read from serial port.")
        response = msgspec.json.decode(resp_str, type=Acknowledge)
        if response.qid != qid:
            raise RuntimeError(f"Invalid response from laser. Received: {response}")
