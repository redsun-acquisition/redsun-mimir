from __future__ import annotations

import time
from concurrent.futures import Future
from typing import TYPE_CHECKING

import msgspec
from bluesky.protocols import Reading
from redsun.device import Device
from redsun.engine import Status
from redsun.log import Loggable
from redsun.storage import PrepareInfo, register_metadata
from redsun.utils.descriptors import make_descriptor, make_key, make_reading
from serial import Serial

import redsun_mimir.device.youseetoo.utils as uc2utils
from redsun_mimir.protocols import LightProtocol, MotorProtocol

from ._actions import Acknowledge, LaserAction, MotorAction, MotorResponse

if TYPE_CHECKING:
    from typing import Any, ClassVar, Final

    from bluesky.protocols import Descriptor, Location, Reading


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
        self.enabled = False
        self.intensity = 0
        self.id = 1
        self.qid = 1

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
        self.intensity = value
        if self.enabled:
            self._send_command(
                LaserAction(
                    id=self.id,
                    qid=self.qid,
                    value=self.intensity,
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
        self.enabled = not self.enabled
        if self.enabled:
            action = LaserAction(
                id=self.id,
                qid=self.qid,
                value=self.intensity,
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
        if self.enabled:
            self._send_command(
                LaserAction(
                    id=self.id,
                    qid=self.qid,
                    value=0,
                ),
                Status(),
            )

    def prepare(self, value: PrepareInfo) -> Status:
        """Contribute laser metadata to the acquisition metadata registry."""
        s = Status()
        register_metadata(
            self.name,
            {
                "light_wavelength": self.wavelength,
                "light_intensity": self.intensity,
                "light_enabled": self.enabled,
            },
        )
        s.set_finished()
        return s

    def describe(self) -> dict[str, Descriptor]:
        descriptor: dict[str, Descriptor] = {
            make_key(self.name, "intensity"): make_descriptor(
                "value", "number", units=self.egu
            ),
            make_key(self.name, "enabled"): {
                "source": "value",
                "dtype": "boolean",
                "shape": [],
            },
        }
        return descriptor

    def read(self) -> dict[str, Reading[Any]]:
        reading: dict[str, Reading[Any]] = {
            make_key(self.name, "intensity"): make_reading(self.intensity, time.time()),
            make_key(self.name, "enabled"): make_reading(self.enabled, time.time()),
        }
        return reading

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


class MimirMotorDevice(Device, MotorProtocol, Loggable):
    """Mimir interface for a motor stage.

    Parameters
    ----------
    name: `str`
        Name of the model.
    egu: `str`
        Engineering unit for the motor stage. Supported values are "nm", "um", "μm", "mm".
        Default is "um".
    step_sizes: `dict[str, float]`
        Step sizes for the motor stage for each axis. The keys of the dictionary should be
        the axis names (e.g. "X", "Y", "Z") and the values should be the step sizes in the specified
        engineering unit. Default is {"X": 100.0, "Y": 100.0, "Z": 100.0}.

    Attributes
    ----------
    motor_step: `int`, frozen
        Step size of the motor in nanometers.
        This is a constant value internal to the motor movement
        operations, and is not configurable by the user.
        Set to 320 nm by default.
    """

    # conversion factor for the engineering units
    # used by the Mimir stage; the final steps the motor
    # executes is computed as follows:
    #   steps = value * self._map[model_info.egu] // self.motor_step
    # where
    # - `value` is the input value the engineering unit
    # - `self._conversion_map[model_info.egu]` is the conversion factor
    _conversion_map: ClassVar[dict[str, int]] = {
        "nm": NM_TO_NM,
        "um": UM_TO_NM,
        "μm": UM_TO_NM,
        "mm": MM_TO_NM,
    }

    _axis_id_map: ClassVar[dict[str, int]] = {
        "X": 1,
        "Y": 2,
        "Z": 3,
    }

    motor_step: Final[int] = 320

    def __init__(
        self,
        name: str,
        /,
        egu: str = "um",
        step_sizes: dict[str, float] = {"X": 100.0, "Y": 100.0, "Z": 100.0},
    ) -> None:
        if egu not in self._conversion_map.keys():
            raise ValueError(
                f"Invalid engineering unit: {egu}"
                f"Supported units are: {list(self._conversion_map.keys())}"
            )

        super().__init__(
            name,
            egu=egu,
            step_sizes=step_sizes,
        )

        # protocol attributes
        self.egu = egu
        self.step_sizes = step_sizes
        self.axis: list[str] = ["X", "Y", "Z"]
        self._active_axis = self.axis[0]

        def callback(future: Future[Serial]) -> None:
            self._serial = future.result()
            self.logger.debug("Serial port ready.")

        serial_or_future: Serial | Future[Serial] = MimirSerialDevice.get()

        if isinstance(serial_or_future, Future):
            serial_or_future.add_done_callback(callback)
        else:
            self._serial = serial_or_future
            self.logger.debug("Serial port ready.")

        # set the conversion factor from egu to steps;
        # it will be used to convert the input value
        # to the number of steps the motor should execute
        self._factor = self._conversion_map[self.egu]

        self._positions: dict[str, Location[float]] = {
            axis: {"setpoint": 0.0, "readback": 0.0} for axis in self.axis
        }

        # set the current axis to the first axis
        self._active_axis = self.axis[0]

    def set(self, value: Any, **kwargs: Any) -> Status:
        s = Status()
        propr = kwargs.get("prop", None) or kwargs.get("propr", None)
        if propr is not None:
            self.logger.info("Setting property %s to %s.", propr, value)
            if propr == "axis" and isinstance(value, str):
                self._active_axis = value
                s.set_finished()
                return s
            elif propr == "step_size" and isinstance(value, float):
                # in truth this does not have a real effect on the motor,
                # but for consistency (and if in the future we serialize
                # the model information) we allow to set the step size
                self.step_sizes[self._active_axis] = value
                s.set_finished()
                return s
            else:
                s.set_exception(ValueError(f"Invalid property: {propr}"))
                return s
        else:
            if not isinstance(value, int | float):
                s.set_exception(ValueError("Value must be a float or int."))
                return s

        # update the setpoint position for the current axis
        self._positions[self._active_axis]["setpoint"] = value
        steps = int(value * self._factor) // self.motor_step

        self.logger.debug(f"Moving motor along {self._active_axis} of {steps} steps.")

        action = MotorAction(
            movement=MotorAction.generate_movement(
                id=self._axis_id_map[self._active_axis], position=steps
            ),
            qid=self._axis_id_map[self._active_axis],
        )
        s.add_callback(self._update_readback)
        self._send_command(action, s)
        return s

    def locate(self) -> Location[float]:
        """Locate mock model."""
        return self._positions[self._active_axis]

    def read_configuration(self) -> dict[str, Reading[Any]]:
        timestamp = time.time()
        config: dict[str, Reading[Any]] = {
            make_key(self.name, "egu"): make_reading(self.egu, timestamp),
            make_key(self.name, "axis"): make_reading(self.axis, timestamp),
        }
        for ax, step in self.step_sizes.items():
            config[make_key(self.name, f"{ax}_step_size")] = make_reading(
                step, timestamp
            )
        return config

    def describe_configuration(self) -> dict[str, Descriptor]:
        descriptors: dict[str, Descriptor] = {
            make_key(self.name, "egu"): make_descriptor(
                "settings", "string", readonly=True
            ),
            make_key(self.name, "axis"): make_descriptor(
                "settings", "array", shape=[len(self.axis)], readonly=True
            ),
        }
        for ax in self.axis:
            key = make_key(self.name, f"{ax}_step_size")
            descriptors[key] = make_descriptor("settings", "number")
        return descriptors

    def shutdown(self) -> None: ...

    def prepare(self, _: PrepareInfo) -> Status:
        """Contribute motor metadata to the acquisition metadata registry."""
        s = Status()
        md: dict[str, Any] = {}
        for axis in self.axis:
            md[f"position_{axis.lower()}"] = self._positions[axis]["readback"]
            md[f"motor_step_size_{axis.lower()}"] = self.step_sizes.get(axis, 0.0)
        md["motor_egu"] = self.egu
        register_metadata(self.name, md)
        s.set_finished()
        return s

    def _send_command(self, command: MotorAction, status: Status) -> None:
        """Send a command to the motor stage.

        Parameters
        ----------
        command: `MotorAction`
            Command to send to the motor stage.
        status: `Status`
            Status object associated to the command.
        """
        packet = msgspec.json.encode(command)
        written = self._serial.write(packet)
        self.logger.debug(f"Sent command: {packet.decode()}")
        if written is None or written != len(packet):
            status.set_exception(ValueError("Failed to write to serial port."))
            return
        # wait for the acknowledge response
        # and clean it up
        # to remove unwanted characters
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
        # wait for the motor response
        # and clean it up
        # to remove unwanted characters
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

    def _update_readback(self, status: Status) -> None:
        """Update the currently active axis readback position.

        When the status object is set as finished successfully,
        the readback position is updated to match the setpoint.

        Parameters
        ----------
        status : Status
            The status object associated with the callback.

        """
        if status.success:
            self._positions[self._active_axis]["readback"] = self._positions[
                self._active_axis
            ]["setpoint"]
