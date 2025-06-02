from __future__ import annotations

import time
from typing import TYPE_CHECKING

import msgspec
from serial import Serial
from sunflare.engine import Status
from sunflare.log import Loggable
from sunflare.model import Model

from redsun_mimir.protocols import LightProtocol, MotorProtocol

from ._actions import Acknowledge, LaserAction, MotorAction, MotorResponse
from ._config import MimirSerialInfo

if TYPE_CHECKING:
    from typing import Any, Callable, ClassVar, Final

    from bluesky.protocols import Descriptor, Location, Reading

    from redsun_mimir.model import StageModelInfo

    from ._config import MimirLaserInfo


class _SerialFactory:
    """Factory class to create the serial object.

    Provides Mimir device components with a reference
    to the serial port to which the device is connected,
    and the encoder/decoder to use for serial communication.

    Attributes
    ----------
    serial: `Serial`
        Serial object to use for communication with the Mimir device.
    encoder: `msgspec.json.Encoder`
        Encoder to use for serial communication with the Mimir device.
    decoder: `msgspec.json.Decoder`
        Decoder to use for serial communication with the Mimir device.
    callbacks: `list[Callable[[Serial, Encoder, Decoder], None]]`
        List of callbacks to be called when the serial object is created.
    """

    serial: ClassVar[Serial | None] = None
    callbacks: ClassVar[list[Callable[[Serial], None]]] = []

    @classmethod
    def setup(cls, info: MimirSerialInfo) -> None:
        """Create the serial object.

        Parameters
        ----------
        info: `MimirSerialInfo`
            Serial information to setup the serial object.
        """
        cls.serial = Serial(
            port=info.port,
            baudrate=info.bauderate,
            timeout=info.timeout,
        )
        for callback in cls.callbacks:
            callback(cls.serial)
        cls.callbacks.clear()

    @classmethod
    def get(cls, callback: Callable[[Serial], None]) -> None:
        """Get the serial object.

        Registers callbacks to provide the callers with
        references to:
        - the serial object;
        - the `msgspec` encoder;
        - the `msgspec` decoder.
        If the serial object is not yet created,
        the callback will be stored and invoked when it is created.
        Otherwise, the callback will be called immediately
        with the newly created serial object.

        The callback function should have the following signature:

        .. code-block:: python
            def callback(serial: Serial, Encoder, Decoder) -> None:
                # do something with the serial object
                ...

        Parameters
        ----------
        callback: `Callable[[Serial, Encoder, Decoder], None]`
            Callback function to be called with the serial object.
        """
        if cls.serial is None:
            cls.callbacks.append(callback)
            return
        callback(cls.serial)


class MimirSerialModel(Model[MimirSerialInfo]):
    """Mimir interface for serial communication.

    This model is in charge of setting up the serial
    communication with a Mimir device. It does not provide
    direct interaction with the device, but rather opens the
    serial port and provides it to other models.

    .. warning::

        Currently it is not exposed to the user.
        In the future an appropriate serial stack
        (widget and controller) should be provided.

    Parameters
    ----------
    name: `str`
        Name of the model.
    model_info: `LightModelInfo`

    """

    def __init__(self, name: str, model_info: MimirSerialInfo) -> None:
        super().__init__(name, model_info)
        _SerialFactory.setup(model_info)


class MimirLaserModel(LightProtocol, Loggable):
    """Mimir interface for a laser source.

    Parameters
    ----------
    name: `str`
        Name of the model.
    model_info: `MimirLaserInfo`
        Model information for the laser source.
    """

    def __init__(self, name: str, model_info: MimirLaserInfo) -> None:
        if model_info.binary:
            raise ValueError("Mimir laser does not support binary mode.")
        if model_info.intensity_range is None:
            raise ValueError("Mimir laser requires an intensity range.")
        if model_info.intensity_range[0] < 0 or model_info.intensity_range[1] > 1023:
            raise ValueError("Mimir laser intensity range must be between 0 and 1023.")

        self._name = name
        self._model_info = model_info
        self.enabled = False
        self.intensity = 0

        self._serial: Serial
        self._expected_response: Acknowledge
        self._response_length: int

        def _get_serial(serial: Serial) -> None:
            self._serial = serial
            self._expected_response = Acknowledge(self.model_info.qid)

        _SerialFactory.get(_get_serial)

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
                    id=self._model_info.id,
                    qid=self._model_info.qid,
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
        action: LaserAction

        s = Status()
        self.enabled = not self.enabled
        if self.enabled:
            action = LaserAction(
                id=self._model_info.id,
                qid=self._model_info.qid,
                value=self.intensity,
            )
        else:
            action = LaserAction(
                id=self._model_info.id,
                qid=self._model_info.qid,
                value=0,
            )
        self._send_command(action, s)
        return s

    @property
    def model_info(self) -> MimirLaserInfo:
        """The model information for the laser source."""
        return self._model_info

    @property
    def name(self) -> str:
        """The name of the laser source."""
        return self._name

    @property
    def parent(self) -> None:
        """The parent of the laser source.

        For Bluesky compatibility only.
        """
        return None

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
        return self.model_info.read_configuration()

    def describe_configuration(self) -> dict[str, Descriptor]:
        """Describe the configuration of the laser source.

        Returns
        -------
        `dict[str, Any]`
            Dictionary with the configuration of the laser source.
        """
        return self.model_info.describe_configuration()


NM_TO_NM: Final[int] = 1
UM_TO_NM: Final[int] = 1_000
MM_TO_NM: Final[int] = 1_000_000


class MimirMotorModel(MotorProtocol, Loggable):
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

    motor_step: Final[int] = 320

    # conversion factor for the engineering units
    # used by the Mimir stage; the final steps the motor
    # executes is computed as follows:
    #   steps = value * self._map[model_info.egu] // self.motor_step
    # where
    # - `value` is the input value the engineering unit
    # - `self._conversion_map[model_info.egu]` is the conversion factor

    _conversion_map: Final[dict[str, int]] = {
        "nm": NM_TO_NM,
        "um": UM_TO_NM,
        "μm": UM_TO_NM,
        "mm": MM_TO_NM,
    }

    _axis_id_map: Final[dict[str, int]] = {
        "X": 1,
        "Y": 2,
        "Z": 3,
    }

    def __init__(self, name: str, model_info: StageModelInfo) -> None:
        if model_info.egu not in ["nm", "mm", "um", "μm"]:
            err_msg = (
                f"Invalid engineering unit for Mimir motor: {model_info.egu}. "
                "Supported units are 'nm', 'mm', 'um', 'μm'."
            )
            self.logger.exception(err_msg)
            raise ValueError(err_msg)

        if not all(axis in self._axis_id_map for axis in model_info.axis):
            err_msg = (
                f"Invalid axis names in model info: {model_info.axis}. "
                f"Supported axes are: {list(self._axis_id_map.keys())}."
            )
            self.logger.exception(err_msg)
            raise ValueError(err_msg)

        self._name = name
        self._model_info = model_info

        # set the conversion factor from egu to steps;
        # it will be used to convert the input value
        # to the number of steps the motor should execute
        self._factor: Final[int] = self._conversion_map[model_info.egu]

        self._serial: Serial

        self._positions: dict[str, Location[float]] = {
            axis: {"setpoint": 0.0, "readback": 0.0} for axis in model_info.axis
        }

        # set the current axis to the first axis
        self.axis = self.model_info.axis[0]

        def _get_serial(serial: Serial) -> None:
            self._serial = serial

        _SerialFactory.get(_get_serial)

    def set(self, value: Any, **kwargs: Any) -> Status:
        s = Status()
        propr = kwargs.get("prop", None)
        if propr is not None:
            self.logger.info("Setting property %s to %s.", propr, value)
            if propr == "axis" and isinstance(value, str):
                self.axis = value
                s.set_finished()
                return s
            elif propr == "step_size" and isinstance(value, int | float):
                self.model_info.step_sizes[self.axis] = value
                s.set_finished()
                return s
            else:
                s.set_exception(ValueError(f"Invalid property: {propr}"))
                return s
        else:
            if not isinstance(value, int | float):
                s.set_exception(ValueError("Value must be a float or int."))
                return s

        # convert the value to steps;
        # the value is in engineering units,
        # and the motor step is in nanometers;
        # the conversion factor is stored in self._factor
        steps = int(value * self._factor) // self.motor_step
        action = MotorAction(
            movement=MotorAction.generate_movement(
                id=self._axis_id_map[self.axis], position=steps
            ),
            qid=self._axis_id_map[self.axis],
        )
        self._send_command(action, s)
        return s

    def locate(self) -> Location[float]:
        """Locate mock model."""
        return self._positions[self.axis]

    def read_configuration(self) -> dict[str, Reading[Any]]:
        """Read mock configuration."""
        return self.model_info.read_configuration()

    def describe_configuration(self) -> dict[str, Descriptor]:
        """Describe mock configuration."""
        return self.model_info.describe_configuration()

    @property
    def parent(self) -> None:
        return None

    @property
    def name(self) -> str:  # noqa: D102
        return self._name

    @property
    def model_info(self) -> StageModelInfo:  # noqa: D102
        return self._model_info

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
        # wait for the response
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
        response = msgspec.json.decode(resp_str, type=Acknowledge)
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
        motor_response = msgspec.json.decode(motor_resp_str, type=MotorResponse)
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
