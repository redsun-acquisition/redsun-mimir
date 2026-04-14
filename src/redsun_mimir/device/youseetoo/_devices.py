from __future__ import annotations

import time
from concurrent.futures import Future
from typing import TYPE_CHECKING

import msgspec
from bluesky.protocols import Reading
from redsun.device import Device, SoftAttrRW
from redsun.engine import Status
from redsun.log import Loggable
from redsun.utils.descriptors import make_descriptor, make_key, make_reading
from serial import Serial

import redsun_mimir.device.youseetoo.utils as uc2utils
from redsun_mimir.device.axis import MotorAxis
from redsun_mimir.protocols import LightProtocol

from ._actions import Acknowledge, LaserAction, MotorAction, MotorResponse

if TYPE_CHECKING:
    from typing import Any, ClassVar, Final

    from bluesky.protocols import Descriptor, Reading
    from redsun.storage import PrepareInfo


class MimirSerialDevice(Device, Loggable):
    """Mimir interface for serial communication.

    This model is in charge of setting up the serial
    communication with a Mimir device. It does not provide
    direct interaction with the device, but rather opens the
    serial port and provides it to other models.

    Parameters
    ----------
    name: `str`
        Name of the model.
    port: `str`
        Serial port to use for communication.
    bauderate: `int`
        Baud rate for serial communication.
    timeout: `float`
        Timeout for serial communication in seconds.
        Default is 3.0 s.
    """

    # as the serial port needs to be shared between devices
    # via a class method, it gets stored as a class variable
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
        super().__init__(name, port=port, bauderate=bauderate, timeout=timeout)

        # we could wrap the serial creation in a
        # try-except block to catch potential errors;
        # but actually we want the app to crash if the
        # serial port cannot be opened, because without
        # it the device can't work at all
        try:
            MimirSerialDevice._serial = Serial(
                port=port,
                baudrate=bauderate,
                timeout=timeout,
            )
        except Exception as e:
            raise RuntimeError(f"Failed to open serial port: {e}") from e
        if MimirSerialDevice._serial is not None:
            self._instance_serial = MimirSerialDevice._serial
        if len(MimirSerialDevice._futures) > 0:
            # if there are futures waiting for the serial to be ready,
            # set the result for all of them
            for future in MimirSerialDevice._futures:
                future.set_result(self._instance_serial)
            MimirSerialDevice._futures.clear()

        # do an hard reset of the serial port,
        # to ensure that the device is ready
        self._instance_serial.dtr = False
        self._instance_serial.rts = True
        time.sleep(0.5)
        self._instance_serial.dtr = False
        self._instance_serial.rts = False
        # give it abundant time to reset; we might lose
        # some output from the reset process
        # which would cause follow-up comms to fail
        time.sleep(2.0)
        reset_bytes = self._instance_serial.read_until(expected=b"{'setup': 'done'}")
        if reset_bytes is not None:
            response = reset_bytes.decode(errors="ignore").strip()
            self.logger.info("Serial reset response")
            for line in response.splitlines():
                self.logger.info(line)

    def read_configuration(self) -> dict[str, Reading[Any]]:
        # TODO: for now we don't return anything...
        # eventually there should be a reusable
        # presenter / view stack to show / update
        # the configuration of background devices like this one
        return {}

    def describe_configuration(self) -> dict[str, Descriptor]:
        return {}

    def shutdown(self) -> None:
        """Shutdown the serial communication.

        This method is called when the application is closed.
        """
        if self._instance_serial.is_open:
            self._instance_serial.close()

    @classmethod
    def get(cls) -> Serial | Future[Serial]:
        """Get the serial object.

        Returns
        -------
        Serial | Future[Serial]
            Serial object to use for communication with the Mimir device.
            If the serial port is not ready yet (i.e. the app hasn't built
            the device yet), a Future object is returned which will be set when the
            serial port is ready.
        """
        if cls._serial is None:
            # the app hasn't built it yet; we create a future
            # object which will be set when the app will build
            # the serial; we return the future object to the
            # caller so that it can wait for the serial to be ready before
            # using it
            future: Future[Serial] = Future()
            cls._futures.add(future)
            return future

        return cls._serial


class MimirLaserDevice(Device, LightProtocol, Loggable):
    """Mimir interface for a laser source.

    Parameters
    ----------
    name: `str`
        Name of the model.
    model_info: `MimirLaserInfo`
        Model information for the laser source.
    """

    def __init__(
        self,
        name: str,
        /,
        wavelength: int = 0,
        egu: str = "mW",
        intensity_range: tuple[int, ...] = (0, 1023),
        step_size: int = 1,
    ) -> None:
        super().__init__(
            name,
            wavelength=wavelength,
            egu=egu,
            intensity_range=intensity_range,
            step_size=step_size,
        )

        # protocol attributes
        self.binary = False
        self.wavelength = wavelength
        self.egu = egu
        self.intensity_range = intensity_range
        self.step_size = step_size
        self.id = 1
        self.qid = 1

        # SoftAttrRW for the mutable state attrs; auto-named by Device.__setattr__
        self.enabled: SoftAttrRW[bool] = SoftAttrRW[bool](False)
        self.intensity: SoftAttrRW[int] = SoftAttrRW[int](0, units=egu)

        def callback(future: Future[Serial]) -> None:
            self._serial = future.result()
            self.logger.debug("Serial port ready.")

        serial_or_future: Serial | Future[Serial] = MimirSerialDevice.get()

        if isinstance(serial_or_future, Future):
            serial_or_future.add_done_callback(callback)
        else:
            self._serial = serial_or_future
            self.logger.debug("Serial port ready.")

    def set(self, value: Any, **kwargs: Any) -> Status:
        """Set the intensity of the laser source.

        .. note::

            `**kwargs` are ignored in this implementation.

        Parameters
        ----------
        value: `Any`
            `int` value to set the intensity of the laser source.

        Returns
        -------
        `Status`
            Status of the command.
        """
        s = Status()
        if kwargs:
            # mimir laser does not support custom properties
            s.set_exception(ValueError("device does not support custom properties."))
            return s
        if not isinstance(value, int):
            s.set_exception(
                ValueError("Value must be an integer number between 0 and 1023.")
            )
            return s

        # keep the new value stored;
        # if the laser is enabled, set
        # the new intensity immediately;
        # otherwise it will be set when
        # `trigger` is called to enable the laser
        self.intensity.set(value)
        if self.enabled.get_value():
            self._send_command(
                LaserAction(
                    id=self.id,
                    qid=self.qid,
                    value=value,
                ),
                s,
            )
        else:
            # the laser is not enabled yet;
            # return the status as finished
            s.set_finished()
        return s

    def trigger(self) -> Status:
        """Toggle the activation status of the light source.

        Returns
        -------
        `Status`
            Status of the command.
        """
        s = Status()
        new_state = not self.enabled.get_value()
        self.enabled.set(new_state)
        if new_state:
            action = LaserAction(
                id=self.id,
                qid=self.qid,
                value=self.intensity.get_value(),
            )
        else:
            action = LaserAction(
                id=self.id,
                qid=self.qid,
                value=0,
            )
        self._send_command(action, s)
        return s

    def _send_command(self, command: LaserAction, status: Status) -> None:
        """Send a command to the laser source.

        Parameters
        ----------
        command: `LaserAction`
            Command to send to the laser source.
        status: `Status`
            Status object associated to the command.
        """
        packet = msgspec.json.encode(command)
        written = self._serial.write(packet)
        self.logger.debug(f"Sent command: {packet.decode()}")
        if written is None or written != len(packet):
            status.set_exception(ValueError("Failed to write to serial port."))
            return
        # wait for the response
        # and clean it up
        # to remove unwanted characters
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
            status.set_exception(ValueError("Failed to read from serial port."))
            return

        self.logger.debug(f"Received response: {resp_str}")
        response = msgspec.json.decode(resp_str, type=Acknowledge)
        if response.qid != command.qid:
            status.set_exception(
                ValueError(f"Invalid response from laser. Received: {response}")
            )
            return

        self._serial.reset_input_buffer()
        status.set_finished()

    def shutdown(self) -> None:
        """Shutdown the laser source.

        This method is called when the application is closed.
        """
        # if the laser is enabled, disable it
        # and set the intensity to 0
        if self.enabled.get_value():
            self._send_command(
                LaserAction(
                    id=self.id,
                    qid=self.qid,
                    value=0,
                ),
                Status(),
            )

    def prepare(self, value: PrepareInfo) -> Status:
        """No-op: device metadata is forwarded via handle_descriptor_metadata."""
        s = Status()
        s.set_finished()
        return s

    def describe(self) -> dict[str, Descriptor]:
        return {**self.intensity.describe(), **self.enabled.describe()}

    def read(self) -> dict[str, Reading[Any]]:
        return {**self.intensity.read(), **self.enabled.read()}

    def read_configuration(self) -> dict[str, Reading[Any]]:
        timestamp = time.time()
        return {
            make_key(self.name, "wavelength"): make_reading(self.wavelength, timestamp),
            make_key(self.name, "binary"): make_reading(self.binary, timestamp),
            make_key(self.name, "egu"): make_reading(self.egu, timestamp),
            make_key(self.name, "intensity_range"): make_reading(
                list(self.intensity_range), timestamp
            ),
            make_key(self.name, "step_size"): make_reading(self.step_size, timestamp),
        }

    def describe_configuration(self) -> dict[str, Descriptor]:
        return {
            make_key(self.name, "wavelength"): make_descriptor(
                "settings", "integer", units="nm", readonly=True
            ),
            make_key(self.name, "binary"): make_descriptor(
                "settings", "string", readonly=True
            ),
            make_key(self.name, "egu"): make_descriptor(
                "settings", "string", readonly=True
            ),
            make_key(self.name, "intensity_range"): make_descriptor(
                "settings", "array", shape=[2], readonly=True
            ),
            make_key(self.name, "step_size"): make_descriptor("settings", "integer"),
        }


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
        super().__init__(name, egu, step_size)
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

    def set(self, value: float, **_kwargs: Any) -> Status:
        """Move this axis by *value* (relative step).

        Parameters
        ----------
        value :
            Step distance in the axis engineering unit.

        Returns
        -------
        Status
            Completes after the Mimir hardware acknowledges the move.
        """
        s = Status()
        self.position.set(self.position.get_value() + value)
        steps = int(value * self._factor) // _MOTOR_STEP
        self.logger.debug(f"Moving {self.name} by {steps} steps.")
        action = MotorAction(
            movement=MotorAction.generate_movement(id=self._axis_id, position=steps),
            qid=self._axis_id,
        )
        self._send_command(action, s)
        return s

    def _send_command(self, command: MotorAction, status: Status) -> None:
        packet = msgspec.json.encode(command)
        written = self._serial.write(packet)
        self.logger.debug(f"Sent command: {packet.decode()}")
        if written is None or written != len(packet):
            status.set_exception(ValueError("Failed to write to serial port."))
            return
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
            status.set_exception(ValueError("Failed to read from serial port."))
            return
        self.logger.debug(f"Received response: {resp_str}")
        try:
            response = msgspec.json.decode(resp_str, type=Acknowledge)
        except msgspec.DecodeError as e:
            status.set_exception(e)
            return
        if response.qid != command.qid:
            status.set_exception(
                ValueError(f"Invalid response from motor. Received: {response}")
            )
            return
        motor_resp_str = (
            str(self._serial.read_until(expected=b"--"))
            .replace("+", "")
            .replace("-", "")
            .replace("\\r", "")
            .replace("\\n", "")
            .replace("b'", "")
            .replace("'", "")
        )
        self.logger.debug(f"Received motor response: {motor_resp_str}")
        if not motor_resp_str:
            status.set_exception(
                ValueError("Failed to read motor response from serial port.")
            )
            return
        try:
            motor_response = msgspec.json.decode(motor_resp_str, type=MotorResponse)
        except msgspec.DecodeError as e:
            status.set_exception(e)
            return
        if motor_response.qid != command.qid:
            status.set_exception(
                ValueError(
                    f"Invalid response from motor. Expected qid {command.qid}, "
                    f"but received {motor_response.qid}."
                )
            )
            return
        self._serial.reset_input_buffer()
        status.set_finished()


class MimirMotorDevice(Device, Loggable):
    """Container device for Mimir motor stage axes.

    Validates the engineering unit, constructs one
    [`MimirMotorAxis`][redsun_mimir.device.youseetoo.MimirMotorAxis] per
    entry in *step_sizes*, and exposes them as typed child attributes
    (``device.x``, ``device.y``, ``device.z``).

    All movement logic lives in the individual axis objects.
    ``read_configuration`` and ``describe_configuration`` aggregate from
    all child axes.

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
        super().__init__(name, egu=egu, step_sizes=step_sizes)
        factor = self._conversion_map[egu]
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

    def read_configuration(self) -> dict[str, Reading[Any]]:
        """Aggregate read() from all child axes."""
        result: dict[str, Reading[Any]] = {}
        for _, axis in self.children():
            if isinstance(axis, MimirMotorAxis):
                result.update(axis.read())
        return result

    def describe_configuration(self) -> dict[str, Descriptor]:
        """Aggregate describe() from all child axes."""
        result: dict[str, Descriptor] = {}
        for _, axis in self.children():
            if isinstance(axis, MimirMotorAxis):
                result.update(axis.describe())
        return result

    def shutdown(self) -> None: ...

    def prepare(self, _: PrepareInfo) -> Status:
        """No-op: device metadata is forwarded via handle_descriptor_metadata."""
        s = Status()
        s.set_finished()
        return s
