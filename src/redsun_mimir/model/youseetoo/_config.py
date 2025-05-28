from __future__ import annotations

from enum import IntEnum

from attrs import define, field, setters, validators
from sunflare.config import ModelInfo

from .._config import LightModelInfo, StageModelInfo


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


@define(kw_only=True)
class MimirLaserInfo(LightModelInfo):
    """Configuration of a Mimir laser.

    Attributes
    ----------
    id: `int`
        ID of the laser (ranging from 0 to 3).
    qid: `int`, optional
        UC2 queue ID for tracking the actions.
        Must be a non-zero positive integer.
        Defaults to 1.
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
        if not isinstance(value, int):
            raise TypeError("Laser ID must be an integer.")
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
        if value < 1:
            raise ValueError("Laser QID must be a positive, non-zero integer.")


@define(kw_only=True)
class MimirStageInfo(StageModelInfo):
    """Configuration of a Mimir stage.

    Attributes
    ----------
    id: `int`
        ID of the stage (ranging from 0 to 3).
    qid: `int`, optional
        UC2 queue ID for tracking the actions.
        Must be a non-zero positive integer.
        Defaults to 1.
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
        if not isinstance(value, int):
            raise TypeError("Motor ID must be an integer.")
        if value < 0 or value > 3:
            raise ValueError("Motor ID must be between 0 and 3.")

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
            raise TypeError("Motor QID must be an integer.")
        if value < 1:
            raise ValueError("Motor QID must be a positive, non-zero integer.")
