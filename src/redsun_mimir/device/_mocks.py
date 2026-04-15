from __future__ import annotations

from ophyd_async.core import (
    AsyncStatus,
    SignalR,
    SignalRW,
    StandardReadable,
    StandardReadableFormat,
    soft_signal_r_and_setter,
    soft_signal_rw,
)
from redsun.log import Loggable

from redsun_mimir.protocols import LightProtocol


class MockLightDevice(StandardReadable, LightProtocol[float], Loggable):
    """Mock light source for simulation and testing purposes.

    Parameters
    ----------
    name :
        Identity key of the device.
    binary :
        Whether the source is on/off only (no analogue intensity).
    wavelength :
        Wavelength in nanometres.
    egu :
        Engineering unit for intensity (stored in the ``intensity`` signal's
        ``units`` descriptor field).
    intensity_range :
        ``(min, max)`` intensity values (stored in the ``intensity`` signal's
        ``limits`` descriptor field via the soft-signal metadata).
    step_size :
        Initial intensity step size.
    """

    intensity: SignalRW[float]
    step_size: SignalRW[float]
    wavelength: SignalR[int]
    binary: SignalR[bool]
    enabled: SignalR[bool]

    def __init__(
        self,
        name: str,
        /,
        *,
        binary: bool = False,
        wavelength: int = 0,
        egu: str = "mW",
        intensity_range: tuple[int | float, ...] | list[int | float] = (0.0, 100.0),
        step_size: int | float = 1,
    ) -> None:
        _intensity_range = tuple(intensity_range)
        self._validate_intensity_range(binary, _intensity_range)

        # Readable signals: intensity + enabled appear in read() output
        with self.add_children_as_readables():
            self.intensity = soft_signal_rw(float, initial_value=0.0, units=egu)
            _enabled, self._set_enabled = soft_signal_r_and_setter(
                bool, initial_value=False
            )
            self.enabled = _enabled

        # Config signals: step_size, wavelength, binary appear in read_configuration()
        with self.add_children_as_readables(StandardReadableFormat.CONFIG_SIGNAL):
            self.step_size = soft_signal_rw(
                float, initial_value=float(step_size), units=egu
            )
            _wavelength, _ = soft_signal_r_and_setter(int, initial_value=wavelength)
            self.wavelength = _wavelength
            _binary, _ = soft_signal_r_and_setter(bool, initial_value=binary)
            self.binary = _binary

        super().__init__(name=name)
        self.logger.info("Initialized")

    @staticmethod
    def _validate_intensity_range(binary: bool, value: tuple[int | float, ...]) -> None:
        if binary and value == (0.0, 0.0):
            return
        if len(value) != 2:
            raise AttributeError(
                f"Length of intensity range must be 2: {value} has length {len(value)}"
            )
        if not all(isinstance(v, (float, int)) for v in value):
            raise AttributeError(
                f"All values in the intensity range must be floats or ints: {value}"
            )
        if value[0] > value[1]:
            raise AttributeError(f"Min value is greater than max value: {value}")
        if not binary and value[0] == value[1]:
            raise AttributeError(
                f"Non-binary device must have a non-degenerate intensity range "
                f"(min != max), got: {value}"
            )

    @AsyncStatus.wrap
    async def trigger(self) -> None:
        """Toggle the activation status of the light source."""
        current = await self.enabled.get_value()
        self._set_enabled(not current)

    def shutdown(self) -> None: ...
