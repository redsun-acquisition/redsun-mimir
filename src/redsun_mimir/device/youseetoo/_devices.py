from __future__ import annotations

import asyncio
import time
from concurrent.futures import Future
from enum import IntEnum
from typing import TYPE_CHECKING

from ophyd_async.core import (
    AsyncStatus,
    SignalBackend,
    StandardReadable,
    StandardReadableFormat,
    soft_signal_r_and_setter,
    soft_signal_rw,
)
from redsun.engine import get_shared_loop
from redsun.log import Loggable
from serial import Serial

from ._backend import uc2_axis_signal, uc2_laser_signal

if TYPE_CHECKING:
    from typing import ClassVar

    from ophyd_async.core import SignalR, SignalRW


class BaudeRate(IntEnum):
    """Baud rates for serial communication.

    It is used for validating the input value from
    the configuration file.
    """

    BR4800 = 4800
    BR9600 = 9600
    BR19200 = 19200
    BR38400 = 38400
    BR57600 = 57600
    BR115200 = 115200
    BR230400 = 230400
    BR460800 = 460800
    BR921600 = 921600


class UC2Serial(StandardReadable, Loggable):
    """Mimir interface for serial communication.

    Opens the serial port and makes it available to other device models via
    the class-level [`get`][redsun_mimir.device.youseetoo.UC2Serial.get]
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
        if bauderate not in BaudeRate.__members__.values():
            self.logger.error(
                f"Invalid baud rate {bauderate}. "
                f"Valid values are: {list(BaudeRate.__members__.values())}"
                f"Setting to default value {BaudeRate.BR115200.value}."
            )
            bauderate = BaudeRate.BR115200.value

        try:
            UC2Serial._serial = Serial(
                port=port,
                baudrate=bauderate,
                timeout=timeout,
            )
        except Exception as e:
            raise RuntimeError(f"Failed to open serial port: {e}") from e

        self._instance_serial = UC2Serial._serial
        if len(UC2Serial._futures) > 0:
            for future in UC2Serial._futures:
                future.set_result(self._instance_serial)
            UC2Serial._futures.clear()

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
            [`UC2Serial`][redsun_mimir.device.youseetoo.UC2Serial]
            is built.
        """
        if cls._serial is None:
            future: Future[Serial] = Future()
            cls._futures.add(future)
            return future
        return cls._serial


class UC2LaserDevice(StandardReadable, Loggable):
    """Interface for UC2 laser source."""

    intensity: SignalRW[int]
    wavelength: SignalR[int]
    enabled: SignalRW[bool]

    def __init__(self, name: str, /, wavelength: int = 0, units: str = "mW") -> None:
        def _callback(future: Future[Serial]) -> None:
            self._serial = future.result()
            self.logger.debug("Serial port ready.")

        serial_or_future: Serial | Future[Serial] = UC2Serial.get()
        if isinstance(serial_or_future, Future):
            serial_or_future.add_done_callback(_callback)
        else:
            self._serial = serial_or_future
            self.logger.debug("Serial port ready.")

        with self.add_children_as_readables():
            self.intensity = uc2_laser_signal(
                self._serial, laser_id=1, units=units, range=(0, 1023)
            )

        with self.add_children_as_readables(StandardReadableFormat.CONFIG_SIGNAL):
            self.wavelength, _ = soft_signal_r_and_setter(int, initial_value=wavelength)
            self.enabled = soft_signal_rw(bool, initial_value=False)
        self._current_intensity = 0
        super().__init__(name)

    @AsyncStatus.wrap
    async def trigger(self) -> None:
        """Trigger the laser to apply the current settings."""
        enabled = await self.enabled.get_value()
        if enabled:
            # laser currently active; stash the current value
            # and set to 0
            self._current_intensity = await self.intensity.get_value()
            await self.intensity.set(0)
        else:
            # laser currently inactive; restore the stashed value
            await self.intensity.set(self._current_intensity)
        await self.enabled.set(not enabled)

    # TODO: HasShutdown must be made async
    def shutdown(self) -> None:
        backend_or_cache = self.enabled._backend_or_cache()
        if isinstance(backend_or_cache, SignalBackend):
            asyncio.run_coroutine_threadsafe(
                backend_or_cache.put(False), get_shared_loop()
            )


class UC2MotorDevice(StandardReadable, Loggable):
    """UC2 motor device."""

    def __init__(self, name: str) -> None:
        def _callback(future: Future[Serial]) -> None:
            self._serial = future.result()
            self.logger.debug("Serial port ready.")

        serial_or_future: Serial | Future[Serial] = UC2Serial.get()
        if isinstance(serial_or_future, Future):
            serial_or_future.add_done_callback(_callback)
        else:
            self._serial = serial_or_future
            self.logger.debug("Serial port ready.")

        with self.add_children_as_readables(StandardReadableFormat.HINTED_SIGNAL):
            self.x = uc2_axis_signal(
                self._serial, axis_id=1, units="mm", range=(-100.0, 100.0)
            )
            self.y = uc2_axis_signal(
                self._serial, axis_id=2, units="mm", range=(-100.0, 100.0)
            )
            self.z = uc2_axis_signal(
                self._serial, axis_id=3, units="mm", range=(-100.0, 100.0)
            )

        super().__init__(name)
