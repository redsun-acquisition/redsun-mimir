from __future__ import annotations

import time
from typing import TYPE_CHECKING

import msgspec
from attrs import define, field, setters, validators
from redsun.device import Device
from redsun.engine import Status
from redsun.log import Loggable
from serial import Serial

import redsun_mimir.device.utils as utils
import redsun_mimir.device.youseetoo.utils as uc2utils
from redsun_mimir.protocols import LightProtocol, MotorProtocol

from ._actions import Acknowledge, LaserAction, MotorAction, MotorResponse

if TYPE_CHECKING:
    from typing import Any, Final

    from bluesky.protocols import Descriptor, Location, Reading


@define(kw_only=True, init=False)
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

    name: str
    port: str = field(
        on_setattr=setters.frozen,
        validator=validators.instance_of(str),
    )
    bauderate: int = field(
        default=uc2utils.BaudeRate.BR115200.value,
        on_setattr=setters.frozen,
    )
    timeout: float = field(
        default=3.0,
        on_setattr=setters.frozen,
        validator=validators.instance_of(float),
    )

    @bauderate.validator
    def _check_baud_rate(self, _: str, value: int) -> None:
        """Check if the baud rate is valid.

        Parameters
        ----------
        attribute: `str`
            Attribute name (unused).
        value: `int`
            Value to check.
        """
        if value not in uc2utils.BaudeRate.__members__.values():
            raise ValueError(
                f"Invalid baud rate {value}. "
                f"Valid values are: {list(uc2utils.BaudeRate.__members__.values())}"
            )

    def __init__(self, name: str, /, **kwargs: Any) -> None:
        super().__init__(name, **kwargs)
        self.__attrs_init__(name=name, **kwargs)
        self._serial = Serial(
            port=self.port,
            baudrate=self.bauderate,
            timeout=self.timeout,
        )

        # do an hard reset of the serial port,
        # to ensure that the device is ready
        self._serial.dtr = False
        self._serial.rts = True
        time.sleep(0.1)
        self._serial.dtr = False
        self._serial.rts = False
        time.sleep(0.5)

    @classmethod
    def get(cls) -> Serial:
        """Get the serial object.

        Returns
        -------
        `Serial`
            Serial object to use for communication with the Mimir device.
        """
        if cls._serial is None:
            raise ValueError("Serial object is not initialized.")
        return cls._serial


@define(kw_only=True, init=False)
class MimirLaserDevice(Device, LightProtocol, Loggable):
    """Mimir interface for a laser source.

    Parameters
    ----------
    name: `str`
        Name of the model.
    model_info: `MimirLaserInfo`
        Model information for the laser source.
    """

    name: str
    binary: bool = field(
        init=False,
        default=False,
        metadata={"description": "Binary mode operation."},
    )
    wavelength: int = field(
        default=0,
        validator=validators.instance_of(int),
        metadata={"description": "Wavelength in nm."},
    )
    egu: str = field(
        default="mW",
        validator=validators.instance_of(str),
        on_setattr=setters.frozen,
        metadata={"description": "Engineering units."},
    )
    intensity_range: tuple[int | float, ...] = field(
        init=False,
        default=(0, 1023),
        metadata={"description": "Intensity range (min, max)."},
    )
    step_size: int = field(
        default=1,
        validator=validators.instance_of(int),
        metadata={"description": "Step size for the intensity."},
    )

    # injected serial object;
    # it should be created at app level
    _serial: Serial = field(init=False, repr=False, factory=MimirSerialDevice.get)

    def __init__(self, name: str, /, **kwargs: Any) -> None:
        super().__init__(name, **kwargs)
        self.__attrs_init__(name=name, **kwargs)
        self.enabled = False
        self.intensity = 0
        self.id = 0
        self.qid = 1

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
        # shutdown should be delegated
        # to the serial model, which will
        # which will close the serial port
        ...

    def read(self) -> dict[str, Reading[Any]]:
        """Read the current state of the laser source.

        Returns
        -------
        `dict[str, Any]`
            Dictionary with the current state of the laser source.
        """
        return {
            "intensity": {"value": self.intensity, "timestamp": time.time()},
            "enabled": {"value": self.enabled, "timestamp": time.time()},
        }

    def describe(self) -> dict[str, Descriptor]:
        return {
            "intensity": {
                "source": self.name,
                "dtype": "number",
                "shape": [],
            },
            "enabled": {
                "source": self.name,
                "dtype": "boolean",
                "shape": [],
            },
        }

    def read_configuration(self) -> dict[str, Reading[Any]]:
        """Read the configuration of the laser source.

        Returns
        -------
        `dict[str, Any]`
            Dictionary with the configuration of the laser source.
        """
        return {}

    def describe_configuration(self) -> dict[str, Descriptor]:
        """Describe the configuration of the laser source.

        Returns
        -------
        `dict[str, Any]`
            Dictionary with the configuration of the laser source.
        """
        return {}


NM_TO_NM: Final[int] = 1
UM_TO_NM: Final[int] = 1_000
MM_TO_NM: Final[int] = 1_000_000


@define(kw_only=True, init=False)
class MimirMotorDevice(Device, MotorProtocol, Loggable):
    """Mimir interface for a motor stage.

    Parameters
    ----------
    name: `str`
        Name of the model.
    model_info: `MimirStageInfo`
        Model information for the motor stage.

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

    name: str
    egu: str = field(
        default="mm",
        validator=validators.instance_of(str),
        on_setattr=setters.frozen,
        metadata={"description": "Engineering units."},
    )

    @egu.validator
    def _check_egu(self, _: str, value: str) -> None:
        if value not in ["nm", "mm", "um", "μm"]:
            raise ValueError(
                f"Invalid engineering unit for Mimir motor: {value}. "
                "Supported units are 'nm', 'mm', 'um', 'μm'."
            )

    axis: list[str] = field(
        init=False,
        default=["X", "Y", "Z"],
        validator=validators.instance_of(list),
        on_setattr=setters.frozen,
        metadata={"description": "Axis names."},
    )
    step_sizes: dict[str, float] = field(
        validator=validators.instance_of(dict),
        metadata={"description": "Step sizes for each axis."},
    )
    limits: dict[str, tuple[float, float]] | None = field(
        default=None,
        converter=utils.convert_limits,
        metadata={"description": "Limits for each axis."},
    )
    motor_step: int = field(
        init=False,
        default=320,
        on_setattr=setters.frozen,
    )

    _conversion_map: dict[str, int] = field(
        init=False,
        on_setattr=setters.frozen,
        default={
            "nm": NM_TO_NM,
            "um": UM_TO_NM,
            "μm": UM_TO_NM,
            "mm": MM_TO_NM,
        },
    )

    _axis_id_map: dict[str, int] = field(
        init=False,
        on_setattr=setters.frozen,
        default={
            "X": 1,
            "Y": 2,
            "Z": 3,
        },
    )

    # injected serial object;
    # it should be created at app level
    _serial: Serial = field(init=False, repr=False, factory=MimirSerialDevice.get)

    def __init__(self, name: str, /, **kwargs: Any) -> None:
        super().__init__(name, **kwargs)
        self.__attrs_init__(name=name, **kwargs)

    def __attrs_post_init__(self) -> None:
        # set the conversion factor from egu to steps;
        # it will be used to convert the input value
        # to the number of steps the motor should execute
        self._factor = self._conversion_map[self.egu]

        self._serial: Serial

        self._positions: dict[str, Location[float]] = {
            axis: {"setpoint": 0.0, "readback": 0.0} for axis in self.axis
        }

        # set the current axis to the first axis
        self._active_axis = self.axis[0]

    def set(self, value: Any, **kwargs: Any) -> Status:
        s = Status()
        propr = kwargs.get("prop", None)
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

        self.logger.debug(f"Moving motor along {self.axis} of {steps} steps.")

        action = MotorAction(
            movement=MotorAction.generate_movement(
                id=self._axis_id_map[self._active_axis], position=steps
            ),
            qid=self._axis_id_map[self._active_axis],
        )
        self._send_command(action, s)
        return s

    def locate(self) -> Location[float]:
        """Locate mock model."""
        return self._positions[self._active_axis]

    def read_configuration(self) -> dict[str, Reading[Any]]:
        """Read mock configuration."""
        return {}

    def describe_configuration(self) -> dict[str, Descriptor]:
        """Describe mock configuration."""
        return {}

    def shutdown(self) -> None: ...

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
        s : Status
            The status object associated with the callback.

        """
        if status.success:
            self._positions[self._active_axis]["readback"] = self._positions[
                self._active_axis
            ]["setpoint"]
