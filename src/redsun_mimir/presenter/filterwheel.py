from __future__ import annotations

from typing import TYPE_CHECKING

from redsun.aio import run_coro
from redsun.device.protocols import HasAsyncShutdown
from redsun.log import Loggable
from redsun.presenter import Presenter
from redsun.virtual import slot

from redsun_mimir.protocols import StatedProtocol
from redsun_mimir.providers import STATED_CONFIGURATION, STATED_DESCRIPTION

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    from bluesky.protocols import Descriptor, Reading
    from ophyd_async.core import Device
    from redsun.virtual import VirtualContainer


class FilterWheelPresenter(Presenter, Loggable):
    """Presenter for filter wheel position control.

    Forwards selection requests from
    [`FilterWheelView`][redsun_mimir.view.FilterWheelView] to the underlying
    devices. The names a wheel accepts are published in its descriptor, so the
    view never needs a position index.

    Parameters
    ----------
    name :
        Identity key of the presenter.
    devices :
        Mapping of device names to device instances.
    timeout :
        Status wait timeout in seconds. Defaults to ``2.0``.
    """

    def __init__(
        self,
        name: str,
        devices: Mapping[str, Device],
        /,
        timeout: float | None = None,
    ) -> None:
        super().__init__(name, devices)
        self._timeout: float = timeout or 2.0

        self._wheels: dict[str, StatedProtocol] = {
            name: device
            for name, device in devices.items()
            if isinstance(device, StatedProtocol)
        }
        if not self._wheels:
            self.logger.warning("No device found.")
        else:
            names = ", ".join(self._wheels)
            self.logger.debug(f"Found devices: {names}")

    def device_configuration(self) -> dict[str, Reading[Any]]:
        """Get the current configuration readings of all stated devices.

        Returns
        -------
        dict[str, Reading[Any]]
            Flat mapping of canonical keys to their current readings.
        """
        result: dict[str, Reading[Any]] = {}
        for wheel in self._wheels.values():
            result.update(run_coro(wheel.read_configuration()))
        return result

    def device_description(self) -> dict[str, Descriptor]:
        """Get the configuration descriptors of all stated devices.

        Returns
        -------
        dict[str, Descriptor]
            Flat mapping of canonical keys to their descriptors.
        """
        result: dict[str, Descriptor] = {}
        for wheel in self._wheels.values():
            result.update(run_coro(wheel.describe_configuration()))
        return result

    def register_providers(self, container: VirtualContainer) -> None:
        """Register stated device info as a provider in the DI container."""
        container.provide(STATED_CONFIGURATION, self.device_configuration())
        container.provide(STATED_DESCRIPTION, self.device_description())
        container.register_signals(self)

    @slot
    async def set_state(self, name: str, state: str) -> None:
        """Select *state* on the wheel named *name*.

        Parameters
        ----------
        name : str
            Name of the stated device.
        state : str
            Name of the position to select, as the device labels it.
        """
        await self._wheels[name].state.set(state, self._timeout)

    def shutdown(self) -> None:
        """Shutdown the presenter and all stated devices."""
        for wheel in self._wheels.values():
            if isinstance(wheel, HasAsyncShutdown):
                run_coro(wheel.shutdown())
