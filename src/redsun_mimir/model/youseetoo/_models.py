from __future__ import annotations

from typing import TYPE_CHECKING

from msgspec.json import Decoder, Encoder
from serial import Serial
from sunflare.engine import Status
from sunflare.model import Model

from redsun_mimir.protocols import LightProtocol

from ._config import LaserAction, LaserActionResponse, SerialInfo

if TYPE_CHECKING:
    from typing import Any, Callable, ClassVar

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
    def setup(cls, info: SerialInfo) -> None:
        """Create the serial object.

        Parameters
        ----------
        info: `SerialInfo`
            Serial information to setup the serial object.
        """
        cls.serial = Serial(
            port=info.port,
            baudrate=info.baude_rate,
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


class MimirSerialModel(Model[SerialInfo]):
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

    def __init__(self, name: str, model_info: SerialInfo) -> None:
        self._name = name
        self._model_info = model_info
        SerialFactory.setup(model_info)


class MimirLaserModel(LightProtocol):
    """Mimir interface for a laser source.

    Parameters
    ----------
    name: `str`
        Name of the model.
    model_info: `MimirLaserInfo`
        Model information for the laser source.

    Attributes
    ----------
    enabled: `bool`
        Activation status of the light source.
    intensity: `int`
        Intensity of the light source.
    """

    def __init__(self, name: str, model_info: MimirLaserInfo) -> None:
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
            self._response_length = len(self._encoder.encode(self._expected_response))

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
        if written is None or written != len(action):
            status.set_exception(ValueError("Failed to write to serial port."))
            return
        # check the response from the laser
        resp_bytes = self._serial.read(self._response_length)
        if resp_bytes is None or len(resp_bytes) != self._response_length:
            status.set_exception(
                ValueError(
                    f"Failed to read from serial port. Received: {resp_bytes.decode()}"
                )
            )
            return
        response = self._decoder.decode(resp_bytes)
        if response != self._expected_response:
            status.set_exception(
                ValueError(f"Invalid response from laser. Received: {response}")
            )
            return
        status.set_finished()
