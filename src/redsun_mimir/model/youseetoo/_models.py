from __future__ import annotations

from typing import TYPE_CHECKING

from msgspec.json import Decoder, Encoder
from serial import Serial
from sunflare.engine import Status
from sunflare.model import Model

from redsun_mimir.protocols import LightProtocol

from ._config import LaserAction, SerialInfo

if TYPE_CHECKING:
    from typing import Any, Callable, ClassVar

    from ._config import MimirLaserInfo


class SerialFactory:
    serial: ClassVar[Serial | None] = None
    encoder: ClassVar[Encoder] = Encoder()
    decoder: ClassVar[Decoder[LaserAction]] = Decoder(LaserAction)
    callbacks: ClassVar[
        list[Callable[[Serial, Encoder, Decoder[LaserAction]], None]]
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
        )
        for callback in cls.callbacks:
            callback(cls.serial, cls.encoder, cls.decoder)

    @classmethod
    def get(
        cls, callback: Callable[[Serial, Encoder, Decoder[LaserAction]], None]
    ) -> None:
        """Get the serial object.

        Uses a callback system to provide the callers with the
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
        self._decoder: Decoder[LaserAction]

        def _get_serial(
            serial: Serial, encoder: Encoder, decoder: Decoder[LaserAction]
        ) -> None:
            self._serial = serial
            self._encoder = encoder
            self._decoder = decoder

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
        self.intensity = value
        s.set_finished()
        return s

    def trigger(self) -> Status:
        """Toggle the activation status of the light source.

        Returns
        -------
        `Status`
            Status of the command.
        """
        action: bytes
        written: int | None

        s = Status()
        self.enabled = not self.enabled
        if self.enabled:
            # if the light is enabled, set the laser intensity
            # to the current value set in self.intensity
            action = self._encoder.encode(
                LaserAction(
                    id=self._model_info.id,
                    value=self.intensity,
                )
            )
            written = self._serial.write(action)
            if written is None or written != len(action):
                s.set_exception(ValueError("Failed to write to serial port."))
                return s
        else:
            # if the light is disabled, set the laser intensity to 0
            action = self._encoder.encode(
                LaserAction(
                    id=self._model_info.id,
                    value=0,
                )
            )
            written = self._serial.write(action)
            if written is None or written != len(action):
                s.set_exception(ValueError("Failed to write to serial port."))
                return s
        s.set_finished()
        return s

    @property
    def model_info(self) -> MimirLaserInfo:
        """The model information for the laser source."""
        return self._model_info

    @property
    def name(self) -> str:
        """The name of the laser source."""
        return self._name
