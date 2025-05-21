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

    BR4800 = 4800
    BR9600 = 9600
    BR19200 = 19200
    BR38400 = 38400
    BR57600 = 57600
    BR115200 = 115200
    BR230400 = 230400
    BR460800 = 460800
    BR921600 = 921600


@define(kw_only=True)
class MimirSerialInfo(ModelInfo):
    """Model information for Mimir device serial communication.

    Attributes
    ----------
    port: `str`
        Serial port to use for communication.
    bauderate: `int`
        Baud rate for serial communication.
    timeout: `float`
        Timeout for serial communication in seconds.
        Default is 0.5 s.
    """

    port: str = field(
        on_setattr=setters.frozen,
        validator=validators.instance_of(str),
    )
    bauderate: int = field(
        default=BaudeRate.BR115200.value,
        on_setattr=setters.frozen,
    )
    timeout: float = field(
        default=0.5,
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


        tag_name = tag_action(LaserAction.__name__)
        # tag_name will be "/laser_act"

    The `tag` field is automatically generated
    when subclassing the `Action` struct.

    Parameters
    ----------
    class_name: `str`
        Class name to convert.

    Returns
    -------
    `str`
        Converted command name.
    """
    return "".join(["/", class_name.lower().replace("action", "_act")])


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
    qid: `int`
        UC2 queue ID of the requested action.
    success: `int`
        The success status of the action.
        1: success, 0: failure.
        Defaults to 1 (assuming success).
    """

    qid: int
    success: int = sfield(default=1)


@define(kw_only=True)
class MimirLaserInfo(LightModelInfo):
    """Configuration of a Mimir laser.

    Attributes
    ----------
    id: `int`
        ID of the laser (ranging from 0 to 3).
    qid: `int`, optional
        UC2 queue ID for tracking the actions.
        Must be a positive integer, with 0 allowed.
        Defaults to 0.
    """

    id: int = field(on_setattr=setters.frozen)
    qid: int = field(
        default=1,
        on_setattr=setters.frozen,
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

    @qid.validator
    def _check_qid(self, _: str, value: int) -> None:
        """Check if the QID is valid.

        Valid values are positive integers.

        Parameters
        ----------
        attribute: `str`
            Attribute name (unused).
        value: `int`
            Value to check.
        """
        if not isinstance(value, int):
            raise TypeError("Laser QID must be an integer.")
        if value < 0:
            raise ValueError("Laser QID must be a positive integer.")
