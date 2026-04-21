from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from dependency_injector import providers
from redsun.aio import run_coro
from redsun.device.protocols import HasAsyncShutdown
from redsun.log import Loggable
from redsun.presenter import Presenter
from redsun.utils import find_signals

from redsun_mimir.protocols import LightProtocol  # noqa: TC001

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    from bluesky.protocols import Descriptor, Reading
    from ophyd_async.core import Device
    from redsun.virtual import VirtualContainer


class LightPresenter(Presenter, Loggable):
    """Presenter for light source control.

    Forwards toggle and intensity requests from
    [`LightView`][redsun_mimir.view.LightView] to the underlying
    light devices.

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

        self._lights: dict[str, LightProtocol] = {
            name: device
            for name, device in devices.items()
            if isinstance(device, LightProtocol)
        }
        if not self._lights:
            self.logger.warning("No device found.")
        else:
            names = ", ".join(light.name for light in self._lights.values())
            self.logger.debug(f"Found devices: {names}")

    def device_configuration(self) -> dict[str, Reading[Any]]:
        """Get the current configuration readings of all light devices.

        Returns
        -------
        dict[str, Reading[Any]]
            Flat mapping of canonical keys to their current readings.
        """
        result: dict[str, Reading[Any]] = {}
        for light in self._lights.values():
            result.update(run_coro(light.read_configuration()))
            result.update(run_coro(light.read()))
        return result

    def device_description(self) -> dict[str, Descriptor]:
        """Get the configuration descriptors of all light devices.

        Returns
        -------
        dict[str, Descriptor]
            Flat mapping of canonical keys to their descriptors.
        """
        result: dict[str, Descriptor] = {}
        for light in self._lights.values():
            result.update(run_coro(light.describe_configuration()))
            result.update(run_coro(light.describe()))
        return result

    def register_providers(self, container: VirtualContainer) -> None:
        """Register light model info as a provider in the DI container."""
        container.light_configuration = providers.Object(self.device_configuration())
        container.light_description = providers.Object(self.device_description())
        container.register_signals(self)

    def inject_dependencies(self, container: VirtualContainer) -> None:
        """Connect to the virtual container signals."""
        sigs = find_signals(container, ["sigToggleLightRequest", "sigIntensityRequest"])
        if "sigToggleLightRequest" in sigs:
            sigs["sigToggleLightRequest"].connect(
                lambda name: run_coro(self.trigger(name))
            )
        if "sigIntensityRequest" in sigs:
            sigs["sigIntensityRequest"].connect(
                lambda name, intensity: run_coro(self.set(name, intensity))
            )

    async def trigger(self, name: str) -> None:
        """Toggle a light source and emit the new state on completion."""
        light = self._lights[name]
        await asyncio.wait_for(light.trigger(), timeout=self._timeout)
        state = await light.enabled.get_value()
        self.logger.debug(f"Toggled {name!r} -> enabled={state}")

    async def set(self, name: str, intensity: int | float) -> None:
        """Set the intensity of a light source.

        Parameters
        ----------
        name : str
            Name of the light device.
        intensity : int | float
            New intensity value.
        """
        light = self._lights[name]
        await asyncio.wait_for(light.intensity.set(intensity), timeout=self._timeout)

    def shutdown(self) -> None:
        """Shutdown the presenter and all light devices."""
        for light in self._lights.values():
            if isinstance(light, HasAsyncShutdown):
                run_coro(light.shutdown())
