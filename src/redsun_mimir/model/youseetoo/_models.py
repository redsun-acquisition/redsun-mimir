from __future__ import annotations

import time
from typing import TYPE_CHECKING

from msgspec.json import Decoder, Encoder
from serial import Serial
from sunflare.engine import Status
from sunflare.log import Loggable
from sunflare.model import Model

from redsun_mimir.protocols import LightProtocol

from ._config import LaserAction, LaserActionResponse, MimirSerialInfo

if TYPE_CHECKING:
    from typing import Any, Callable, ClassVar

    from bluesky.protocols import Descriptor, Reading

    from ._config import MimirLaserInfo

DecodingType = LaserActionResponse


class SerialFactory:
    serial: ClassVar[Serial | None] = None
    encoder: ClassVar[Encoder] = Encoder()
    decoder: ClassVar[Decoder[DecodingType]] = Decoder(DecodingType)
    callbacks: ClassVar[
        list[Callable[[Serial, Encoder, Decoder[DecodingType]], None]]
    ] = []

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
            callback(cls.serial, cls.encoder, cls.decoder)
        cls.callbacks.clear()

    @classmethod
    def get(
        cls, callback: Callable[[Serial, Encoder, Decoder[DecodingType]], None]
    ) -> None:
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
        callback(cls.serial, cls.encoder, cls.decoder)


class MimirSerialModel(Model[MimirSerialInfo]):
    """Mimir interface for serial communication.

    This model is in charge of setting up the serial
    communication with a Mimir device. It does not provide
    direct interaction with the device, but rather opens the
    serial port and provides it to other models.

    Parameters
    ----------
    name: `str`
        Name of the model.
    model_info: `LightModelInfo`

    """

    def __init__(self, name: str, model_info: MimirSerialInfo) -> None:
        super().__init__(name, model_info)
        SerialFactory.setup(model_info)


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
        self._encoder: Encoder
        self._decoder: Decoder[DecodingType]
        self._expected_response: LaserActionResponse
        self._response_length: int

        def _get_serial(
            serial: Serial, encoder: Encoder, decoder: Decoder[DecodingType]
        ) -> None:
            self._serial = serial
            self._encoder = encoder
            self._decoder = decoder
            self._expected_response = LaserActionResponse(self.model_info.qid)

        SerialFactory.get(_get_serial)

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
        action = self._encoder.encode(command)
        written = self._serial.write(action)
        self.logger.debug(f"Sent command: {action.decode()}")
        if written is None or written != len(action):
            status.set_exception(ValueError("Failed to write to serial port."))
            return
        # wait for the response
        # and clean it up
        # to remove unwanted characters
        resp_str = (
            str(self._serial.read_until(expected=b"}"))
            .replace("+", "")
            .replace("\\r", "")
            .replace("\\t", "")
            .replace("\\n", "")
            .replace("b'", "")
            .replace("\\", "")
            .replace("'", "")
        )
        if not resp_str:
            status.set_exception(ValueError("Failed to read from serial port."))
            return

        self.logger.debug(f"Received response: {resp_str}")
        response = self._decoder.decode(resp_str)
        if response != self._expected_response:
            status.set_exception(
                ValueError(f"Invalid response from laser. Received: {response}")
            )
            return
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
