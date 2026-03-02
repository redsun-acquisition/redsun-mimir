from __future__ import annotations

import time
from typing import TYPE_CHECKING

from attrs import define, field, setters, validators
from redsun.device import Device
from redsun.engine import Status
from redsun.log import Loggable
from redsun.storage import PrepareInfo, register_metadata
from redsun.utils.descriptors import (
    make_descriptor,
    make_key,
    make_reading,
)

import redsun_mimir.device.utils as utils
from redsun_mimir.protocols import LightProtocol

if TYPE_CHECKING:
    from typing import Any

    from bluesky.protocols import Descriptor, Reading


@define(kw_only=True, init=False, eq=False)
class MockLightDevice(Device, LightProtocol, Loggable):
    """Mock light source for simulation and testing purposes."""

    name: str
    binary: bool = field(
        default=False,
        validator=validators.instance_of(bool),
        metadata={"description": "Binary mode operation."},
    )
    wavelength: int = field(
        default=0,
        validator=validators.instance_of(int),
        metadata={"description": "Wavelength in nm."},
    )
    egu: str = field(
        default="mW",
        validator=validators.instance_of(str),
        on_setattr=setters.frozen,
        metadata={"description": "Engineering units."},
    )
    intensity_range: tuple[int | float, ...] = field(
        default=None,
        converter=utils.convert_to_tuple,
        metadata={"description": "Intensity range (min, max)."},
    )
    step_size: int = field(
        default=1,
        validator=validators.instance_of(int),
        metadata={"description": "Step size for the intensity."},
    )

    @intensity_range.validator
    def _check_range(self, _: str, value: tuple[int | float, ...]) -> None:
        if self.binary and value == (0.0, 0.0):
            return
        if len(value) != 2:
            raise AttributeError(
                f"Length of intensity range must be 2: {value} has length {len(value)}"
            )
        if not all(isinstance(val, (float, int)) for val in value):
            raise AttributeError(
                f"All values in the intensity range must be floats or ints: {value}"
            )
        if value[0] > value[1]:
            raise AttributeError(f"Min value is greater than max value: {value}")
        if not self.binary and value[0] == value[1]:
            raise AttributeError(
                f"Non-binary device must have a non-degenerate intensity range "
                f"(min != max), got: {value}"
            )

    def __init__(self, name: str, /, **kwargs: Any) -> None:
        super().__init__(name, **kwargs)
        self.__attrs_init__(name=name, **kwargs)
        self.enabled = False
        self.intensity = 0.0
        self.logger.info("Initialized")

    def set(self, value: Any, **kwargs: Any) -> Status:
        """Set the intensity of the light source.

        Parameters
        ----------
        value : ``Any``
            New intensity value. Must be of type ``int`` or ``float``.
        **kwargs : ``Any``
            Additional keyword arguments (not used).

        Returns
        -------
        ``Status``
            The status object.
        """
        s = Status()
        if not isinstance(value, int | float):
            s.set_exception(ValueError("Value must be a number."))
            return s
        self.intensity = float(value)
        s.set_finished()
        return s

    def describe(self) -> dict[str, Descriptor]:
        descriptor: dict[str, Descriptor] = {
            make_key(self.name, "intensity"): make_descriptor(
                "value", "number", units=self.egu
            ),
            make_key(self.name, "enabled"): {
                "source": "value",
                "dtype": "boolean",
                "shape": [],
            },
        }
        return descriptor

    def read(self) -> dict[str, Reading[Any]]:
        reading: dict[str, Reading[Any]] = {
            make_key(self.name, "intensity"): make_reading(self.intensity, time.time()),
            make_key(self.name, "enabled"): make_reading(self.enabled, time.time()),
        }
        return reading

    def read_configuration(self) -> dict[str, Reading[Any]]:
        timestamp = time.time()
        return {
            make_key(self.name, "wavelength"): make_reading(self.wavelength, timestamp),
            make_key(self.name, "binary"): make_reading(self.binary, timestamp),
            make_key(self.name, "egu"): make_reading(self.egu, timestamp),
            make_key(self.name, "intensity_range"): make_reading(
                list(self.intensity_range), timestamp
            ),
            make_key(self.name, "step_size"): make_reading(self.step_size, timestamp),
        }

    def describe_configuration(self) -> dict[str, Descriptor]:
        return {
            make_key(self.name, "wavelength"): make_descriptor(
                "settings", "integer", units="nm", readonly=True
            ),
            make_key(self.name, "binary"): make_descriptor(
                "settings", "string", readonly=True
            ),
            make_key(self.name, "egu"): make_descriptor(
                "settings", "string", readonly=True
            ),
            make_key(self.name, "intensity_range"): make_descriptor(
                "settings", "array", shape=[2], readonly=True
            ),
            make_key(self.name, "step_size"): make_descriptor("settings", "integer"),
        }

    def shutdown(self) -> None: ...

    def prepare(self, value: PrepareInfo) -> Status:
        """Contribute light metadata to the acquisition metadata registry."""
        s = Status()
        register_metadata(
            self.name,
            {
                "light_wavelength": self.wavelength,
                "light_intensity": self.intensity,
                "light_enabled": self.enabled,
            },
        )
        s.set_finished()
        return s

    def trigger(self) -> Status:
        """Toggle the activation status of the light source."""
        self.enabled = not self.enabled
        s = Status()
        s.set_finished()
        return s
