from __future__ import annotations

import time
from typing import TYPE_CHECKING

from redsun.device import Device, SoftAttrRW
from redsun.engine import Status
from redsun.log import Loggable
from redsun.utils.descriptors import (
    make_descriptor,
    make_key,
    make_reading,
)

from redsun_mimir.protocols import LightProtocol

if TYPE_CHECKING:
    from typing import Any

    from bluesky.protocols import Descriptor, Reading
    from redsun.storage import PrepareInfo


class MockLightDevice(Device, LightProtocol, Loggable):
    """Mock light source for simulation and testing purposes."""

    def __init__(
        self,
        name: str,
        /,
        *,
        binary: bool = False,
        wavelength: int = 0,
        egu: str = "mW",
        intensity_range: tuple[int | float, ...] | list[int | float] = (0.0, 0.0),
        step_size: int = 1,
    ) -> None:
        super().__init__(name)
        self.binary = binary
        self.wavelength = wavelength
        self.egu = egu
        self.step_size = step_size
        self.intensity_range: tuple[int | float, ...] = tuple(intensity_range)

        self._validate_intensity_range()

        self.enabled: SoftAttrRW[bool] = SoftAttrRW[bool](False)
        self.intensity: SoftAttrRW[float] = SoftAttrRW[float](0.0, units=self.egu)
        self.logger.info("Initialized")

    def _validate_intensity_range(self) -> None:
        value = self.intensity_range
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

    def set(self, value: Any, **_kwargs: Any) -> Status:
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
        if not isinstance(value, int | float):
            s = Status()
            s.set_exception(ValueError("Value must be a number."))
            return s
        return self.intensity.set(float(value))

    def describe(self) -> dict[str, Descriptor]:
        return {**self.intensity.describe(), **self.enabled.describe()}

    def read(self) -> dict[str, Reading[Any]]:
        return {**self.intensity.read(), **self.enabled.read()}

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

    def prepare(self, _: PrepareInfo) -> Status:
        """No-op: device metadata is forwarded via handle_descriptor_metadata."""
        s = Status()
        s.set_finished()
        return s

    def trigger(self) -> Status:
        """Toggle the activation status of the light source."""
        return self.enabled.set(not self.enabled.get_value())
