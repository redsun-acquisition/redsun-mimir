"""YouSeeToo (UC2) signals, built on callable-backed soft signals.

The controller is write-only over its serial link: it acknowledges a command
but offers no way to query the current position or laser power. Each signal
therefore supplies only a ``setter``, and the soft backend's cache holds the
last commanded value.

The serial exchange itself is unchanged; it runs in a worker thread because
`pyserial` is blocking, and under a lock because one port is shared by every
axis and laser.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from functools import cached_property
from typing import TYPE_CHECKING, Final

import msgspec
from ophyd_async.core import (
    MovableLogic,
    StandardMovable,
    StandardReadable,
    soft_signal_r_and_setter,
    soft_signal_rw,
)

from redsun_mimir.device.signals import bounded_soft_signal_rw

from ._actions import Acknowledge, LaserAction, MotorAction, MotorResponse

if TYPE_CHECKING:
    from collections.abc import Callable
    from threading import Lock

    from ophyd_async.core import SignalRW, TimeoutCalculator
    from serial import Serial

    from redsun_mimir.device._logics import AxisType

NM_TO_NM: Final[int] = 1
UM_TO_NM: Final[int] = 1_000
MM_TO_NM: Final[int] = 1_000_000

MOTOR_STEP: Final[int] = 320

_AXIS_ID: Final[dict[str, int]] = {"x": 1, "y": 2, "z": 3}
_CONVERSION: Final[dict[str, int]] = {
    "nm": NM_TO_NM,
    "um": UM_TO_NM,
    "mm": MM_TO_NM,
}


def _clean(raw: bytes) -> str:
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


def _move_axis(
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

        resp_str = _clean(serial.read_until(expected=b"--"))
        if not resp_str:
            raise RuntimeError("Failed to read from serial port.")
        try:
            response = msgspec.json.decode(resp_str, type=Acknowledge)
        except msgspec.DecodeError as e:
            raise RuntimeError(f"Failed to decode response: {e}") from e
        if response.qid != axis_id:
            raise RuntimeError(f"Invalid response from motor. Received: {response}")

        motor_resp_str = _clean(serial.read_until(expected=b"--"))
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


def _set_laser(serial: Serial, lock: Lock, laser_id: int, qid: int, value: int) -> None:
    """Command a laser to *value* and consume its acknowledgement."""
    with lock:
        serial.reset_input_buffer()
        action = LaserAction(id=laser_id, qid=qid, value=value)
        packet = msgspec.json.encode(action)
        written = serial.write(packet)
        if written is None or written != len(packet):
            raise RuntimeError("Failed to write to serial port.")

        resp_str = _clean(serial.read_until(expected=b"}"))
        if not resp_str:
            raise RuntimeError("Failed to read from serial port.")
        response = msgspec.json.decode(resp_str, type=Acknowledge)
        if response.qid != qid:
            raise RuntimeError(f"Invalid response from laser. Received: {response}")


@dataclass
class UC2AxisLogic(MovableLogic[float]):
    """Move logic for a YouSeeToo axis.

    The controller cannot be queried, so ``readback`` is written from the
    commanded value once the serial exchange is acknowledged: ``locate()``
    reports the two as equal because the device cannot tell them apart.
    """

    readback_set: Callable[[float], None] = field(default=lambda _: None)

    async def move(self, new_position: float, timeout: TimeoutCalculator) -> None:
        """Command the axis and adopt the commanded value as the readback."""
        await self.setpoint.set(new_position, timeout=timeout())
        self.readback_set(new_position)


class UC2Axis(StandardReadable, StandardMovable[float]):
    """One axis of a YouSeeToo stage.

    Parameters
    ----------
    serial : Serial
        Serial connection to the YouSeeToo controller.
    axis : AxisType
        Axis to control. Must be one of "x", "y", or "z".
    units : str
        Units for the axis. Must be one of "nm", "um", or "mm".
    lock : threading.Lock
        Lock for synchronizing access to the serial port.
    name : str, optional
        Device name. Assigned by the parent when held in a ``DeviceMap``.
    """

    def __init__(
        self,
        serial: Serial,
        axis: AxisType,
        units: str,
        lock: Lock,
        name: str = "",
    ) -> None:
        axis_id = _AXIS_ID[axis]
        factor = _CONVERSION[units]

        async def setter(value: float | None) -> float | None:
            if value is None:
                return None
            # pyserial is blocking: keep it off the event loop
            await asyncio.to_thread(_move_axis, serial, lock, axis_id, factor, value)
            return value

        with self.add_children_as_readables():
            self.readback, self._readback_set = soft_signal_r_and_setter(
                float, 0.0, units=units
            )
        self.setpoint = soft_signal_rw(float, 0.0, units=units, setter=setter)

        super().__init__(name)

    @cached_property
    def movable_logic(self) -> MovableLogic[float]:
        """Setpoint and echoed readback of this axis."""
        return UC2AxisLogic(
            setpoint=self.setpoint,
            readback=self.readback,
            readback_set=self._readback_set,
        )


def uc2_laser_signal(
    serial: Serial, laser_id: int, units: str, range: tuple[int, int], lock: Lock
) -> SignalRW[int]:
    """Create a `SignalRW` for a YouSeeToo laser.

    Parameters
    ----------
    serial: Serial
        Serial connection to the YouSeeToo controller.
    laser_id: int
        ID of the laser to control. Must be 1 or 2.
    units: str
        Units for the laser power. Must be "mW".
    range: tuple[int, int]
        Valid range for the laser power. E.g. (0, 1000) for 0-1000 mW.
    lock: threading.Lock
        Lock for synchronizing access to the serial port.
    """
    qid = 1

    async def setter(value: int | None) -> int | None:
        if value is None:
            return None
        await asyncio.to_thread(_set_laser, serial, lock, laser_id, qid, int(value))
        return value

    # bounded rather than plain: the light view reads limits.control to size
    # its intensity slider, and ophyd-async cannot express limits on its own
    return bounded_soft_signal_rw(
        range[0],
        range[1],
        units=units,
        initial_value=0,
        datatype=int,
        name=f"laser_{laser_id}_power",
        setter=setter,
    )
