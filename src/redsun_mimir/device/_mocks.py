from __future__ import annotations

from ophyd_async.core import (
    AsyncStatus,
    StandardReadable,
    StandardReadableFormat,
    soft_signal_r_and_setter,
    soft_signal_rw,
)
from redsun.log import Loggable


class MockLightDevice(StandardReadable, Loggable):
    """Mock light source for simulation and testing purposes.

    Parameters
    ----------
    name : str
        Device name.
    wavelength : int, optional
        Wavelength of the light source in nanometers. Defaults to ``0``.
    """

    def __init__(
        self,
        name: str,
        /,
        *,
        wavelength: int = 0,
    ) -> None:
        with self.add_children_as_readables():
            self.intensity = soft_signal_rw(float, initial_value=0.0, units="mW")
            self.enabled = soft_signal_rw(bool, initial_value=False)

        with self.add_children_as_readables(StandardReadableFormat.CONFIG_SIGNAL):
            self.wavelength, _ = soft_signal_r_and_setter(int, initial_value=wavelength)

        super().__init__(name)

    @AsyncStatus.wrap
    async def trigger(self) -> None:
        """Toggle the activation status of the light source."""
        current = await self.enabled.get_value()
        await self.enabled.set(not current)
        self.logger.debug(
            f"{'Enabled' if not current else 'Disabled'} light source {self.name}"
        )
