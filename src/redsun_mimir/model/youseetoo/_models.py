from __future__ import annotations

import time
from collections.abc import Sequence
from typing import TYPE_CHECKING, cast

import msgspec
from bluesky.protocols import Descriptor, Reading
from pymmcore_plus import CMMCorePlus as Core
from serial import Serial
from sunflare.engine import Status
from sunflare.log import Loggable
from sunflare.model import Model

from redsun_mimir.protocols import DetectorProtocol, LightProtocol, MotorProtocol

from ._actions import Acknowledge, LaserAction, MotorAction, MotorResponse
from ._config import MimirSerialInfo

if TYPE_CHECKING:
    from typing import Any, Callable, ClassVar, Final

    from bluesky.protocols import Descriptor, Location, Reading
    from event_model.documents import Dtype

    from redsun_mimir.model import DetectorModelInfo, MotorModelInfo

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

        # do an hard reset of the serial port,
        # to ensure that the device is ready
        cls.serial.dtr = False
        cls.serial.rts = True
        time.sleep(0.1)
        cls.serial.dtr = False
        cls.serial.rts = False
        time.sleep(0.5)

        setup = cls.serial.read_until(expected=b"{'setup':'done'}").decode("utf-8")
        if setup.find("{'setup':'done'}") == -1:
            raise ValueError(
                "Failed to setup the serial port. "
                "The device did not respond with 'setup: done'."
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
        return self.model_info.read_configuration(timestamp=time.time())

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

    def __init__(self, name: str, model_info: MotorModelInfo) -> None:
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
            elif propr == "step_size" and isinstance(value, float):
                # in truth this does not have a real effect on the motor,
                # but for consistency (and if in the future we serialize
                # the model information) we allow to set the step size
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

        # update the setpoint position for the current axis
        self._positions[self.axis]["setpoint"] = value
        steps = int(value * self._factor) // self.motor_step

        self.logger.debug(f"Moving motor along {self.axis} of {steps} steps.")

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
        return self.model_info.read_configuration(timestamp=time.time())

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
    def model_info(self) -> MotorModelInfo:  # noqa: D102
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
            self._positions[self.axis]["readback"] = self._positions[self.axis][
                "setpoint"
            ]


class MimirDetectorModel(DetectorProtocol, Loggable):
    """Mimir detector interface.

    The default device provides a Daheng Imaging camera,
    controlled via the pymmcore-plus package.

    Parameters
    ----------
    name: `str`
        Name of the model.
    model_info: `DetectorModelInfo`
        Model information for the detector.
    """

    # an helper dict to map the actual mmcore properties
    # to more user-friendly names, embedding the
    # egu of each property (if applicable)
    property_map: Final[dict[str, tuple[str, str]]] = {
        "frame rate": ("AcquisitionFrameRate", "fps"),
        "enable frame rate": ("AcquisitionFrameRateMode", ""),
    }
    dtype_map: Final[dict[str, type]] = {
        "boolean": str,  # boolean values are represented as "On" and "Off" strings
        "integer": int,
        "number": float,
        "string": str,
    }

    def __init__(self, name: str, model_info: DetectorModelInfo) -> None:
        self._name = name
        self._model_info = model_info
        self._core = Core()
        try:
            self._core.loadDevice(self.name, "DahengGalaxy", "DahengCamera")
            self._core.initializeDevice(self.name)
            self._core.setCameraDevice(self.name)
            max_height, max_width = (
                int(self._core.getPropertyUpperLimit(self.name, "SensorHeight")),
                int(self._core.getPropertyUpperLimit(self.name, "SensorWidth")),
            )
            if self.model_info.sensor_shape > (max_height, max_width):
                self.logger.warning(
                    f"Provided sensor shape: {self.model_info.sensor_shape[0]}x{self.model_info.sensor_shape[1]}"
                    f"Actual sensor shape: {max_height}x{max_width}."
                    f"Overriding."
                )
                self.model_info.sensor_shape = (max_height, max_width)
            # pre-emptively set the height and width
            # to the input sensor shape; this is useful
            # in case the sensor shape is different
            # from the full view of the camera
            self._core.setProperty(
                self.name, "SensorHeight", self.model_info.sensor_shape[0]
            )
            self._core.setProperty(
                self.name, "SensorWidth", self.model_info.sensor_shape[1]
            )
            self.model_info.serial_number = self._core.getProperty(
                self.name, "CameraID"
            )
            if not self.model_info.vendor:
                self.model_info.vendor = "Micro-Manager"
            self.roi = (0, 0, *self.model_info.sensor_shape)
        except ValueError as e:
            self.logger.exception(e)
            raise e
        except Exception as e:
            self.logger.exception(
                f"Failed to initialize the detector {self.name}. "
                "Ensure that the camera is connected and the drivers are installed."
            )
            raise e

    def read(self) -> dict[str, Reading[Any]]:
        """Read the current state of the detector.

        Returns
        -------
        `dict[str, Reading[Any]]`
            Dictionary with the current state of the detector.
        """
        timestamp = time.time()
        return {
            "buffer": {
                "value": self._core.popNextImage(),
                "timestamp": timestamp,
            },
            "roi": {
                "value": self.roi,
                "timestamp": timestamp,
            },
        }

    def describe(self) -> dict[str, Descriptor]:
        return {
            "buffer": {
                "source": self.name,
                "dtype": "array",
                "shape": [None, None],
            },
            "roi": {
                "source": self.name,
                "dtype": "array",
                "shape": [4],
            },
        }

    def stage(self) -> Status:
        s = Status()
        try:
            self._core.startContinuousSequenceAcquisition(
                float(self._core.getProperty(self.name, "Exposure(us)"))
                / 1000.0  # convert to ms
            )
            self.logger.info(f"Staged detector {self.name} for acquisition.")
            s.set_finished()
        except Exception as e:
            self.logger.exception(f"Failed to stage detector {self.name}: {e}")
            s.set_exception(e)
        return s

    def unstage(self) -> Status:
        s = Status()
        try:
            self._core.stopSequenceAcquisition()
            self.logger.info(f"Unstaged detector {self.name} from acquisition.")
            s.set_finished()
        except Exception as e:
            self.logger.exception(f"Failed to unstage detector {self.name}: {e}")
            s.set_exception(e)
        return s

    def set(self, value: Any, **kwargs: Any) -> Status:
        """Set a property of the detector.

        Parameters
        ----------
        value: `Any`
            The value to set for the property.
        **kwargs: `dict[str, Any]`
            Additional keyword arguments, including the property name.

        Returns
        -------
        `Status`
            Status of the operation.
        """
        s = Status()
        propr = kwargs.get("propr", None)
        if propr is None or (
            propr not in self.property_map and propr != "roi" and propr != "exposure"
        ):
            s.set_exception(ValueError(f"Invalid property: {propr}"))
            return s

        # handle ROI separately
        if propr == "roi":
            if not isinstance(value, Sequence) or len(value) != 4:
                s.set_exception(
                    ValueError(
                        "ROI must be a tuple of 4 integers (x, y, width, height)."
                    )
                )
                return s
            try:
                self._core.setROI(self.name, *value)
                self.roi = tuple(*value)
                s.set_finished()
                self.logger.info(f"Set ROI to {value} for detector {self.name}.")
            except Exception as e:
                self.logger.exception(
                    f"Failed to set ROI for detector {self.name}: {e}"
                )
                s.set_exception(e)
            return s
        if propr == "exposure":
            if not isinstance(value, (int, float)):
                s.set_exception(ValueError("Exposure must be a number."))
                return s
            try:
                self._core.setExposure(self.name, float(value))
                s.set_finished()
                self.logger.info(
                    f"Set exposure to {value} ms for detector {self.name}."
                )
            except Exception as e:
                self.logger.exception(
                    f"Failed to set exposure for detector {self.name}: {e}"
                )
                s.set_exception(e)
            return s

        # handle other properties
        name, _ = self.property_map[propr]
        prop_type = self._core.getPropertyType(self.name, name).to_json()
        if prop_type == "string" and isinstance(value, bool):
            # special case for boolean properties;
            # mmcore uses "On" and "Off" strings
            # to represent boolean values
            value = "On" if value else "Off"
        try:
            self._core.setProperty(self.name, name, self.dtype_map[prop_type](value))
            s.set_finished()
            self.logger.info(f"Set {propr} to {value} for detector {self.name}.")
        except Exception as e:
            self.logger.exception(
                f"Failed to set {propr} for detector {self.name}: {e}"
            )
            s.set_exception(e)
        return s

    def trigger(self) -> Status:
        # should this do anything?
        s = Status()
        s.set_finished()
        return s

    def read_configuration(self) -> dict[str, Reading[Any]]:
        actual_prop: str | bool | int | float
        timestamp = time.time()
        config: dict[str, Reading[Any]] = self.model_info.read_configuration(timestamp)
        for key, value in self.property_map.items():
            prop = self._core.getProperty(self.name, value[0])
            dtype = self._core.getPropertyType(self.name, value[0]).to_json()
            if dtype == "string" and prop in ["On", "Off"]:
                # this is a special case for boolean properties;
                # mmcore uses "On" and "Off" strings
                # to represent boolean values, so we convert them
                dtype = "boolean"
                actual_prop = True if prop == "On" else False
            else:
                actual_prop = prop
            config[key] = {
                "value": self.dtype_map[dtype](actual_prop),
                "timestamp": timestamp,
            }
        config["exposure"] = {
            "value": self._core.getExposure(self.name),
            "timestamp": timestamp,
        }
        return config

    def describe_configuration(self) -> dict[str, Descriptor]:
        config = self.model_info.describe_configuration()
        for key, value in self.property_map.items():
            dtype = cast(
                "Dtype", self._core.getPropertyType(self.name, value[0]).to_json()
            )
            if dtype == "string" and self._core.getProperty(self.name, value[0]) in [
                "On",
                "Off",
            ]:
                # this is a special case for boolean properties;
                # mmcore uses "On" and "Off" strings
                dtype = "boolean"
            descriptor: Descriptor = {
                "source": "settings",
                "dtype": dtype,
                "shape": [],
            }
            if value[1]:
                descriptor["units"] = value[1]
            limits = (
                self._core.getPropertyLowerLimit(self.name, value[0]),
                self._core.getPropertyUpperLimit(self.name, value[0]),
            )
            if limits != (0, 0):
                descriptor["limits"] = {
                    "control": {
                        "low": limits[0],
                        "high": limits[1],
                    }
                }
            config[key] = descriptor
        config["exposure"] = {
            "source": "settings",
            "dtype": "number",
            "shape": [],
            "units": "ms",
            "limits": {
                "control": {
                    "low": float(
                        self._core.getPropertyLowerLimit(self.name, "Exposure(us)")
                    ),
                    "high": float(
                        self._core.getPropertyUpperLimit(self.name, "Exposure(us)")
                    ),
                }
            },
        }
        return config

    @property
    def name(self) -> str:
        """The name of the detector."""
        return self._name

    @property
    def parent(self) -> None:
        """The parent of the detector.

        For Bluesky compatibility only.
        """
        return None

    @property
    def model_info(self) -> DetectorModelInfo:
        """The model information for the detector."""
        return self._model_info
