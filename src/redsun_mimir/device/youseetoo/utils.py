from enum import IntEnum

from attrs import define, field, setters, validators


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
class MimirSerialDevice:
    """Interface to a serial device.

    Attributes
    ----------
    port: `str`
        Serial port to use for communication.
    bauderate: `int`
        Baud rate for serial communication.
    timeout: `float`
        Timeout for serial communication in seconds.
        Default is 3.0 s.
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
        if value not in BaudeRate.__members__.values():
            raise ValueError(
                f"Invalid baud rate {value}. "
                f"Valid values are: {list(BaudeRate.__members__.values())}"
            )
