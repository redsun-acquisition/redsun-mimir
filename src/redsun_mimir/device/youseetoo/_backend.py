from __future__ import annotations

import time
from typing import TYPE_CHECKING

import msgspec
from ophyd_async.core import SignalBackend, SignalRW, make_datakey
from ophyd_async.core._signal_backend import make_metadata

from redsun_mimir.device._common import DEFAULT_TIMEOUT

from ._actions import Acknowledge, LaserAction, MotorAction, MotorResponse

if TYPE_CHECKING:
    from typing import ClassVar, Final

    from bluesky.protocols import Reading
    from event_model import DataKey
    from ophyd_async.core import Callback
    from serial import Serial

    from redsun_mimir.device._common import AxisType

NM_TO_NM: Final[int] = 1
UM_TO_NM: Final[int] = 1_000
MM_TO_NM: Final[int] = 1_000_000

MOTOR_STEP: Final[int] = 320


class UC2AxisSignalBackend(SignalBackend[float]):
    """Signal backend for a YouSeeToo axis."""

    _axis_id_map: ClassVar[dict[str, int]] = {
        "x": 1,
        "y": 2,
        "z": 3,
    }

    _conversion_map: ClassVar[dict[str, int]] = {
        "nm": NM_TO_NM,
        "um": UM_TO_NM,
        "mm": MM_TO_NM,
    }

    def __init__(self, serial: Serial, axis: AxisType, units: str) -> None:
        self.axis = axis
        self.units = units
        self.serial = serial
        self._axis_id = self._axis_id_map[axis]
        self._factor = self._conversion_map[units]
        self._current_position = 0.0
        super().__init__(float)

    def source(self, name: str, read: bool) -> str:
        """Return the source URI for this signal."""
        return f"uc2://{name}_{self.axis}"

    async def connect(self, timeout: float) -> None: ...

    async def put(self, value: float | None) -> None:
        """Write *value* to the MM property."""
        if value is not None:
            await self._send_cmd(value)
            self._current_position = value

    async def get_value(self) -> float:
        """Return the current property value cast to the declared datatype."""
        return await self.get()

    async def get(self) -> float:
        return self._current_position

    async def get_setpoint(self) -> float:
        return await self.get()

    async def get_reading(self) -> Reading[float]:
        """Return a Bluesky Reading with the current value and timestamp."""
        value = await self.get()
        return {"value": value, "timestamp": time.time()}

    async def get_datakey(self, source: str) -> DataKey:
        assert self.datatype is not None, (
            "SignalBackend must have a known datatype to produce a DataKey"
        )
        value = await self.get()
        metadata = make_metadata(self.datatype, units=self.units)
        return make_datakey(self.datatype, value, source, metadata)

    def set_callback(self, callback: Callback[Reading[float]] | None) -> None:
        """Observe changes to the current value, timestamp and severity."""
        # TODO: implement... how?
        ...

    async def _send_cmd(self, value: float) -> None:
        steps = int(value * self._factor / MOTOR_STEP)
        action = MotorAction(
            movement=MotorAction.generate_movement(id=self._axis_id, position=steps),
            qid=self._axis_id,
        )
        packet = msgspec.json.encode(action)
        written = self.serial.write(packet)

        if written is None or written != len(packet):
            raise RuntimeError("Failed to write to serial port.")
        resp_str = (
            str(self.serial.read_until(expected=b"--"))
            .replace("+", "")
            .replace("-", "")
            .replace("\\r", "")
            .replace("\\n", "")
            .replace("b'", "")
            .replace("'", "")
        )
        if not resp_str:
            raise RuntimeError("Failed to read from serial port.")
        try:
            response = msgspec.json.decode(resp_str, type=Acknowledge)
        except msgspec.DecodeError as e:
            raise RuntimeError(f"Failed to decode response: {e}") from e
        if response.qid != self._axis_id:
            raise RuntimeError(f"Invalid response from motor. Received: {response}")

        motor_resp_str = (
            str(self.serial.read_until(expected=b"--"))
            .replace("+", "")
            .replace("-", "")
            .replace("\\r", "")
            .replace("\\n", "")
            .replace("b'", "")
            .replace("'", "")
        )
        if not motor_resp_str:
            raise RuntimeError("Failed to read motor response from serial port.")

        try:
            motor_response = msgspec.json.decode(motor_resp_str, type=MotorResponse)
        except msgspec.DecodeError as e:
            raise RuntimeError(f"Failed to decode motor response: {e}") from e
        if motor_response.qid != self._axis_id:
            raise RuntimeError(
                f"Invalid response from motor. Expected qid {self._axis_id}, "
                f"but received {motor_response.qid}."
            )
        self.serial.reset_input_buffer()


class UC2LaserSignalBackend(SignalBackend[int]):
    """Signal backend for a YouSeeToo laser."""

    def __init__(
        self, serial: Serial, laser_id: int, units: str, range: tuple[int, int]
    ) -> None:
        self.serial = serial
        self.id = laser_id
        self.qid = 1
        self.range = range
        self.units = units
        self._current_value = 0
        super().__init__(int)

    def source(self, name: str, read: bool) -> str:
        """Return the source URI for this signal."""
        return f"uc2://{name}_laser"

    async def connect(self, timeout: float) -> None: ...

    async def put(self, value: int | None) -> None:
        """Write *value* to the MM property."""
        if value is not None:
            await self._send_cmd(value)
            self._current_value = value

    async def get_value(self) -> int:
        """Return the current property value cast to the declared datatype."""
        return await self.get()

    async def get(self) -> int:
        return self._current_value

    async def get_setpoint(self) -> int:
        return await self.get()

    async def get_reading(self) -> Reading[int]:
        """Return a Bluesky Reading with the current value and timestamp."""
        value = await self.get()
        return {"value": value, "timestamp": time.time()}

    async def get_datakey(self, source: str) -> DataKey:
        assert self.datatype is not None, (
            "SignalBackend must have a known datatype to produce a DataKey"
        )
        value = await self.get()
        metadata = make_metadata(self.datatype, units=self.units)
        metadata["limits"] = {"control": {"low": self.range[0], "high": self.range[1]}}
        return make_datakey(self.datatype, value, source, metadata)

    def set_callback(self, callback: Callback[Reading[int]] | None) -> None:
        """Observe changes to the current value, timestamp and severity."""
        # TODO: implement... how?
        ...

    async def _send_cmd(self, value: int) -> None:
        action = LaserAction(id=self.id, qid=self.qid, value=value)
        packet = msgspec.json.encode(action)
        written = self.serial.write(packet)
        if written is None or written != len(packet):
            raise RuntimeError("Failed to write to serial port.")
        resp_str = (
            str(self.serial.read_until(expected=b"}"))
            .replace("+", "")
            .replace("-", "")
            .replace("\\r", "")
            .replace("\\n", "")
            .replace("b'", "")
            .replace("'", "")
        )
        if not resp_str:
            raise RuntimeError("Failed to read from serial port.")
        response = msgspec.json.decode(resp_str, type=Acknowledge)
        if response.qid != self.qid:
            raise RuntimeError(f"Invalid response from laser. Received: {response}")
        self.serial.reset_input_buffer()


def uc2_axis_signal(serial: Serial, axis: AxisType, units: str) -> SignalRW[float]:
    """Create a `SignalRW` for a YouSeeToo axis.

    Parameters
    ----------
    serial: Serial
        Serial connection to the YouSeeToo controller.
    axis: AxisType
        Axis to control. Must be one of "x", "y", or "z".
    units: str
        Units for the axis. Must be one of "nm", "um", or "mm".
    """
    backend = UC2AxisSignalBackend(serial, axis, units)
    return SignalRW(backend, name=f"{axis}_position", timeout=DEFAULT_TIMEOUT)


def uc2_laser_signal(
    serial: Serial, laser_id: int, units: str, range: tuple[int, int]
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
    """
    backend = UC2LaserSignalBackend(serial, laser_id, units, range)
    return SignalRW(backend, name=f"laser_{laser_id}_power", timeout=DEFAULT_TIMEOUT)
