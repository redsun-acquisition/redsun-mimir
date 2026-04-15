from __future__ import annotations

import asyncio
import time
from concurrent.futures import Future
from typing import TYPE_CHECKING, ClassVar, Final

import msgspec
from ophyd_async.core import (
    AsyncStatus,
    SignalR,
    SignalRW,
    StandardReadable,
    StandardReadableFormat,
    soft_signal_r_and_setter,
    soft_signal_rw,
)
from redsun.log import Loggable
from serial import Serial

import redsun_mimir.device.youseetoo.utils as uc2utils
from redsun_mimir.device.axis import MotorAxis
from redsun_mimir.protocols import LightProtocol

from ._actions import Acknowledge, LaserAction, MotorAction, MotorResponse

if TYPE_CHECKING:
    from typing import Any


class MimirSerialDevice(StandardReadable, Loggable):
    """Mimir interface for serial communication.

    Opens the serial port and makes it available to other device models via
    the class-level [`get`][redsun_mimir.device.youseetoo.MimirSerialDevice.get]
    classmethod.

    Parameters
    ----------
    name :
        Identity key of the device.
    port :
        Serial port to open (e.g. ``"COM3"`` or ``"/dev/ttyUSB0"``).
    bauderate :
        Baud rate for serial communication.
    timeout :
        Read timeout in seconds. Defaults to ``1.0``.
    """

    # Shared across all instances and device classes that need serial access
    _serial: ClassVar[Serial | None] = None
    _futures: ClassVar[set[Future[Serial]]] = set()

    def __init__(
        self, name: str, /, port: str, bauderate: int = 115200, timeout: float = 1.0
    ) -> None:
        if bauderate not in uc2utils.BaudeRate.__members__.values():
            self.logger.error(
                f"Invalid baud rate {bauderate}. "
                f"Valid values are: {list(uc2utils.BaudeRate.__members__.values())}"
                f"Setting to default value {uc2utils.BaudeRate.BR115200.value}."
            )
            bauderate = uc2utils.BaudeRate.BR115200.value

        try:
            MimirSerialDevice._serial = Serial(
                port=port,
                baudrate=bauderate,
                timeout=timeout,
            )
        except Exception as e:
            raise RuntimeError(f"Failed to open serial port: {e}") from e

        self._instance_serial = MimirSerialDevice._serial
        if len(MimirSerialDevice._futures) > 0:
            for future in MimirSerialDevice._futures:
                future.set_result(self._instance_serial)
            MimirSerialDevice._futures.clear()

        # Hard reset to ensure the device is ready
        self._instance_serial.dtr = False
        self._instance_serial.rts = True
        time.sleep(0.5)
        self._instance_serial.dtr = False
        self._instance_serial.rts = False
        time.sleep(2.0)
        reset_bytes = self._instance_serial.read_until(expected=b"{'setup': 'done'}")
        if reset_bytes is not None:
            response = reset_bytes.decode(errors="ignore").strip()
            self.logger.info("Serial reset response")
            for line in response.splitlines():
                self.logger.info(line)

        super().__init__(name=name)

    def shutdown(self) -> None:
        """Close the serial port."""
        if self._instance_serial.is_open:
            self._instance_serial.close()

    @classmethod
    def get(cls) -> Serial | Future[Serial]:
        """Return the shared serial object.

        Returns
        -------
        Serial | Future[Serial]
            The open serial port if already initialised, or a
            [`Future`][concurrent.futures.Future] that resolves once
            [`MimirSerialDevice`][redsun_mimir.device.youseetoo.MimirSerialDevice]
            is built.
        """
        if cls._serial is None:
            future: Future[Serial] = Future()
            cls._futures.add(future)
            return future
        return cls._serial


class MimirLaserDevice(StandardReadable, LightProtocol[int], Loggable):
    """Mimir interface for a laser source.

    All observable state is exposed as ophyd-async signals so that
    [`LightPresenter`][redsun_mimir.presenter.LightPresenter] can interact
    with it through the
    [`LightProtocol`][redsun_mimir.protocols.LightProtocol] interface.

    Parameters
    ----------
    name :
        Identity key of the device.
    wavelength :
        Wavelength in nanometres.
    egu :
        Engineering unit for intensity (e.g. ``"mW"``).
    intensity_range :
        ``(min, max)`` intensity values.
    step_size :
        Initial intensity step size.
    """

    intensity: SignalRW[int]
    step_size: SignalRW[int]
    wavelength: SignalR[int]
    binary: SignalR[bool]
    enabled: SignalR[bool]

    def __init__(
        self,
        name: str,
        /,
        wavelength: int = 0,
        egu: str = "mW",
        intensity_range: tuple[int, ...] = (0, 1023),
        step_size: int = 1,
    ) -> None:
        self._wavelength_val = wavelength
        self._egu = egu
        self._intensity_range = intensity_range
        self.id = 1
        self.qid = 1

        # Readable signals: appear in read() / describe() output
        with self.add_children_as_readables():
            self.intensity = soft_signal_rw(int, initial_value=0, units=egu)
            _enabled, self._set_enabled = soft_signal_r_and_setter(
                bool, initial_value=False
            )
            self.enabled = _enabled

        # Config signals: appear in read_configuration() / describe_configuration()
        with self.add_children_as_readables(StandardReadableFormat.CONFIG_SIGNAL):
            self.step_size = soft_signal_rw(int, initial_value=step_size, units=egu)
            _wavelength, _ = soft_signal_r_and_setter(int, initial_value=wavelength)
            self.wavelength = _wavelength
            _binary, _ = soft_signal_r_and_setter(bool, initial_value=False)
            self.binary = _binary

        super().__init__(name=name)

        def _callback(future: Future[Serial]) -> None:
            self._serial = future.result()
            self.logger.debug("Serial port ready.")

        serial_or_future: Serial | Future[Serial] = MimirSerialDevice.get()
        if isinstance(serial_or_future, Future):
            serial_or_future.add_done_callback(_callback)
        else:
            self._serial = serial_or_future
            self.logger.debug("Serial port ready.")

    @AsyncStatus.wrap
    async def trigger(self) -> None:
        """Toggle the activation status of the light source."""
        current = await self.enabled.get_value()
        new_state = not current
        if new_state:
            value = await self.intensity.get_value()
        else:
            value = 0
        await asyncio.to_thread(self._send_laser_sync, value)
        self._set_enabled(new_state)

    def _send_laser_sync(self, value: int) -> None:
        """Send a laser intensity command over serial (blocking)."""
        action = LaserAction(id=self.id, qid=self.qid, value=value)
        packet = msgspec.json.encode(action)
        written = self._serial.write(packet)
        self.logger.debug(f"Sent command: {packet.decode()}")
        if written is None or written != len(packet):
            raise RuntimeError("Failed to write to serial port.")
        resp_str = (
            str(self._serial.read_until(expected=b"}"))
            .replace("+", "")
            .replace("-", "")
            .replace("\\r", "")
            .replace("\\n", "")
            .replace("b'", "")
            .replace("'", "")
        )
        if not resp_str:
            raise RuntimeError("Failed to read from serial port.")
        self.logger.debug(f"Received response: {resp_str}")
        response = msgspec.json.decode(resp_str, type=Acknowledge)
        if response.qid != self.qid:
            raise RuntimeError(f"Invalid response from laser. Received: {response}")
        self._serial.reset_input_buffer()

    def shutdown(self) -> None:
        """Turn off the laser before shutting down."""
        try:
            self._send_laser_sync(0)
        except Exception:
            self.logger.exception("Failed to shutdown laser cleanly.")


NM_TO_NM: Final[int] = 1
UM_TO_NM: Final[int] = 1_000
MM_TO_NM: Final[int] = 1_000_000

_MOTOR_STEP: Final[int] = 320


class MimirMotorAxis(MotorAxis, Loggable):
    """One axis of a Mimir motor stage.

    Sends movement commands over the shared Mimir serial link and tracks
    position via its inherited
    [`position`][redsun_mimir.device.axis.MotorAxis.position] signal.

    Parameters
    ----------
    name :
        Axis name; overwritten by the parent
        [`MimirMotorDevice`][redsun_mimir.device.youseetoo.MimirMotorDevice]
        on assignment.
    egu :
        Engineering unit (``"nm"``, ``"um"``, ``"μm"``, or ``"mm"``).
    step_size :
        Initial step size in the given engineering unit.
    axis_id :
        Numeric axis identifier used in the Mimir serial protocol.
    factor :
        Conversion factor from *egu* to nanometres.
    """

    def __init__(
        self,
        name: str,
        egu: str,
        step_size: float,
        axis_id: int,
        factor: int,
    ) -> None:
        super().__init__(name=name, units=egu, step_size=step_size)
        self._axis_id = axis_id
        self._factor = factor

        def _callback(future: Future[Serial]) -> None:
            self._serial = future.result()
            self.logger.debug("Serial port ready.")

        serial_or_future: Serial | Future[Serial] = MimirSerialDevice.get()
        if isinstance(serial_or_future, Future):
            serial_or_future.add_done_callback(_callback)
        else:
            self._serial = serial_or_future
            self.logger.debug("Serial port ready.")

    @AsyncStatus.wrap
    async def set(self, value: float, **_: Any) -> None:
        """Move this axis by *value* (relative step).

        Parameters
        ----------
        value :
            Step distance in the axis engineering unit.
        """
        current = await self.position.get_value()
        new_pos = current + value
        await asyncio.to_thread(self._send_command_sync, value)
        self._set_position(new_pos)

    def _send_command_sync(self, value: float) -> None:
        """Send a motor move command over serial (blocking)."""
        steps = int(value * self._factor) // _MOTOR_STEP
        self.logger.debug(f"Moving {self.name} by {steps} steps.")
        action = MotorAction(
            movement=MotorAction.generate_movement(id=self._axis_id, position=steps),
            qid=self._axis_id,
        )
        packet = msgspec.json.encode(action)
        written = self._serial.write(packet)
        self.logger.debug(f"Sent command: {packet.decode()}")
        if written is None or written != len(packet):
            raise RuntimeError("Failed to write to serial port.")
        resp_str = (
            str(self._serial.read_until(expected=b"--"))
            .replace("+", "")
            .replace("-", "")
            .replace("\\r", "")
            .replace("\\n", "")
            .replace("b'", "")
            .replace("'", "")
        )
        if not resp_str:
            raise RuntimeError("Failed to read from serial port.")
        self.logger.debug(f"Received response: {resp_str}")
        try:
            response = msgspec.json.decode(resp_str, type=Acknowledge)
        except msgspec.DecodeError as e:
            raise RuntimeError(f"Failed to decode response: {e}") from e
        if response.qid != self._axis_id:
            raise RuntimeError(f"Invalid response from motor. Received: {response}")

        motor_resp_str = (
            str(self._serial.read_until(expected=b"--"))
            .replace("+", "")
            .replace("-", "")
            .replace("\\r", "")
            .replace("\\n", "")
            .replace("b'", "")
            .replace("'", "")
        )
        if not motor_resp_str:
            raise RuntimeError("Failed to read motor response from serial port.")
        self.logger.debug(f"Received motor response: {motor_resp_str}")
        try:
            motor_response = msgspec.json.decode(motor_resp_str, type=MotorResponse)
        except msgspec.DecodeError as e:
            raise RuntimeError(f"Failed to decode motor response: {e}") from e
        if motor_response.qid != self._axis_id:
            raise RuntimeError(
                f"Invalid response from motor. Expected qid {self._axis_id}, "
                f"but received {motor_response.qid}."
            )
        self._serial.reset_input_buffer()


class MimirMotorDevice(StandardReadable, Loggable):
    """Container device for Mimir motor stage axes.

    Validates the engineering unit, constructs one
    [`MimirMotorAxis`][redsun_mimir.device.youseetoo.MimirMotorAxis] per
    entry in *step_sizes*, and exposes them as typed child attributes
    (``device.x``, ``device.y``, ``device.z``).

    All movement logic lives in the individual axis objects.

    Parameters
    ----------
    name :
        Identity key of the device.
    egu :
        Engineering unit. Supported: ``"nm"``, ``"um"``, ``"μm"``, ``"mm"``.
    step_sizes :
        Per-axis step sizes. Keys are axis names (``"x"``, ``"y"``, ``"z"``).
    """

    _conversion_map: ClassVar[dict[str, int]] = {
        "nm": NM_TO_NM,
        "um": UM_TO_NM,
        "μm": UM_TO_NM,
        "mm": MM_TO_NM,
    }

    _axis_id_map: ClassVar[dict[str, int]] = {
        "x": 1,
        "y": 2,
        "z": 3,
    }

    def __init__(
        self,
        name: str,
        /,
        egu: str = "um",
        step_sizes: dict[str, float] = {"x": 100.0, "y": 100.0, "z": 100.0},
    ) -> None:
        if egu not in self._conversion_map:
            raise ValueError(
                f"Invalid engineering unit: {egu}. "
                f"Supported units are: {list(self._conversion_map.keys())}"
            )
        factor = self._conversion_map[egu]
        with self.add_children_as_readables():
            for ax, step_size in step_sizes.items():
                setattr(
                    self,
                    ax,
                    MimirMotorAxis(
                        name=f"{name}-{ax}",
                        egu=egu,
                        step_size=float(step_size),
                        axis_id=self._axis_id_map[ax],
                        factor=factor,
                    ),
                )
        super().__init__(name=name)

    def shutdown(self) -> None: ...
