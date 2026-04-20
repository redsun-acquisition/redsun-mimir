from enum import IntEnum


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
