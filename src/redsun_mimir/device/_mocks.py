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
    wavelength: SignalR[int]
    enabled: SignalRW[bool]

    def __init__(
        self,
        name: str,
        /,
        *,
        wavelength: int = 0,
    ) -> None:
        with self.add_children_as_readables():
            self.intensity = soft_signal_rw(float, initial_value=0.0, units="mW")
            self.enabled, self._set_enabled = soft_signal_rw(bool, initial_value=False)

        with self.add_children_as_readables(StandardReadableFormat.CONFIG_SIGNAL):
            self.wavelength, _ = soft_signal_r_and_setter(int, initial_value=wavelength)

        super().__init__(name=name)
        self.logger.info("Initialized")

    @AsyncStatus.wrap
    async def trigger(self) -> None:
        """Toggle the activation status of the light source."""
        current = await self.enabled.get_value()
        self._set_enabled(not current)

    def shutdown(self) -> None: ...
