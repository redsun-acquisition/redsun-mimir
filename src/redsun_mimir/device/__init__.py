from redsun_mimir.utils.descriptors import (
    make_array_descriptor,
    make_descriptor,
    make_enum_descriptor,
    make_integer_descriptor,
    make_key,
    make_number_descriptor,
    make_reading,
    make_string_descriptor,
    parse_key,
)

from ._mocks import MockLightDevice, MockMotorDevice

__all__ = [
    "MockMotorDevice",
    "MockLightDevice",
    "make_key",
    "parse_key",
    "make_descriptor",
    "make_reading",
    # backwards-compatible wrappers
    "make_number_descriptor",
    "make_integer_descriptor",
    "make_string_descriptor",
    "make_enum_descriptor",
    "make_array_descriptor",
]
