from __future__ import annotations

from enum import IntEnum

from attrs import define, field, setters, validators
from msgspec import UNSET, Struct, UnsetType
from msgspec import field as sfield
from sunflare.config import ModelInfo

from .._config import LightModelInfo


class BaudeRate(IntEnum):
    """Baud rates for serial communication.

    It is used for validating the input value from
    the configuration file.
    """

    BAUD_4800 = 4800
    BAUD_9600 = 9600
    BAUD_19200 = 19200
    BAUD_38400 = 38400
    BAUD_57600 = 57600
    BAUD_115200 = 115200
    BAUD_230400 = 230400
    BAUD_460800 = 460800
    BAUD_921600 = 921600


@define(kw_only=True)
class SerialInfo(ModelInfo):
    """Model information for serial communication.

    Attributes
    ----------
    port: `str`
        Serial port to use for communication.
    baude_rate: `int`
        Baud rate for serial communication.
    timeout: `float`
        Timeout for serial communication in seconds.
        Default is 0.3 s.
    """

    port: str = field(
        on_setattr=setters.frozen,
        validator=validators.instance_of(str),
    )
    baude_rate: int = field(
        on_setattr=setters.frozen,
    )
    timeout: float = field(
        default=0.3,
        on_setattr=setters.frozen,
        validator=validators.instance_of(float),
    )

    @baude_rate.validator
    def _check_baud_rate(self, _: str, value: int) -> None:
        """Check if the baud rate is valid.

        Parameters
        ----------
        attribute: `str`
            Attribute name (unused).
        value: `int`
            Value to check.
        """
        if value not in BaudeRate.__members__.values():
            raise ValueError(
                f"Invalid baud rate {value}. "
                f"Valid values are: {list(BaudeRate.__members__.values())}"
            )


def tag_action(class_name: str) -> str:
    """Create a tag field for the specific action.

    The function output depends on the class name which
    subclasses the `Action` struct.
    The final tag field will be formatted as
    `/<action-name>_act`, where `<action-name>` is the
    lowercase version of the class name, with the
    `Action` suffix removed and replaced with `_act`.

    i.e.

    .. code-block:: python

        class LaserAction(Action):
            pass

        tag_action(LaserAction.__name__) -> "/laser_act"

    Parameters
    ----------
    class_name: `str`
        Class name to convert.

    Returns
    -------
    `str`
        Converted command name.
    """
    return "".join(["/", class_name.lower().replace("command", "_act")])


class Action(Struct, tag_field="task", tag=tag_action): ...


class LaserAction(Action):
    """Mimir light action message.

    Attributes
    ----------
    id: `int`
        ID of the laser command (ranging from 0 to 3).
        Encoded name will be `LASERid`.
    value: int
        Value of the command.
        Encoded name will be `LASERval`.
    qid: `int`, optional
        UC2 queue ID for tracking the command.
    """

    id: int = sfield(name="LASERid")
    value: int = sfield(name="LASERval")
    qid: int | UnsetType = sfield(default=UNSET)


class LaserActionResponse(Struct):
    """Mimir light response message.

    Attributes
    ----------
    success: `int`
        The success status of the action.
        The returned value coincides with the `qid` value
        of the action sent to the device. If the action
        did not provide a `qid` value, the response will
        generate a `qid` value which depends on the internal
        device state.
        For better tracking, the `qid` value should be
        provided in the action.
    """

    success: int


@define(kw_only=True)
class MimirLaserInfo(LightModelInfo):
    """Configuration of a Mimir laser.

    Attributes
    ----------
    id: `int`
        ID of the laser (ranging from 0 to 3).
    qid: `int`, optional
        UC2 queue ID for tracking the actions.
        The value is set to 0 by default.
    """

    id: int = field(on_setattr=setters.frozen)
    qid: int = field(
        default=0,
        on_setattr=setters.frozen,
        validator=validators.instance_of(int),
    )

    @id.validator
    def _check_id(self, _: str, value: int) -> None:
        """Check if the ID is valid.

        Valid values are between 0 and 3.

        Parameters
        ----------
        attribute: `str`
            Attribute name (unused).
        value: `int`
            Value to check.
        """
        if value < 0 or value > 3:
            raise ValueError("Laser ID must be between 0 and 3.")
