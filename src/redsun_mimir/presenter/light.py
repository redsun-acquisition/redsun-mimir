from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from redsun.aio import run_coro
from redsun.log import Loggable
from redsun.presenter import Presenter
from redsun.virtual import slot

from redsun_mimir.protocols import HasAsyncShutdown, LightProtocol
from redsun_mimir.providers import LIGHT_CONFIGURATION, LIGHT_DESCRIPTION

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    from bluesky.protocols import Descriptor, Reading
    from ophyd_async.core import Device
    from redsun.virtual import VirtualContainer


class LightPresenter(Presenter, Loggable):
    """Presenter for light source control.

    Forwards toggle and intensity requests from
    [`LightView`][redsun_mimir.view.LightView] to the light devices.

    Parameters
    ----------
    timeout :
        Status wait timeout in seconds; ``None`` means ``2.0``.
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
        self._locks = {name: asyncio.Lock() for name in self._lights}
        if not self._lights:
            self.logger.warning("No device found.")
        else:
            names = ", ".join(light.name for light in self._lights.values())
            self.logger.debug(f"Found devices: {names}")

    def device_configuration(self) -> dict[str, Reading[Any]]:
        """Return every light's configuration and current readings, by data key."""
        result: dict[str, Reading[Any]] = {}
        for light in self._lights.values():
            result.update(run_coro(light.read_configuration()))
            result.update(run_coro(light.read()))
        return result

    def device_description(self) -> dict[str, Descriptor]:
        """Return every light's configuration and reading descriptors, by data key."""
        result: dict[str, Descriptor] = {}
        for light in self._lights.values():
            result.update(run_coro(light.describe_configuration()))
            result.update(run_coro(light.describe()))
        return result

    def register_providers(self, container: VirtualContainer) -> None:
        """Register the light readings, descriptors and signals with the container."""
        container.provide(LIGHT_CONFIGURATION, self.device_configuration())
        container.provide(LIGHT_DESCRIPTION, self.device_description())
        container.register_signals(self)

    @slot
    async def trigger(self, name: str) -> None:
        """Toggle a light source, serialising requests per light."""
        # toggling reads and flips device state, so two overlapping requests
        # would race; intensity is absolute and needs no such guard
        async with self._locks[name]:
            light = self._lights[name]
            await asyncio.wait_for(light.trigger(), timeout=self._timeout)
            state = await light.enabled.get_value()
            self.logger.debug(f"Toggled {name!r} -> enabled={state}")

    @slot
    async def set(self, name: str, intensity: float) -> None:
        """Set a light's intensity; a binary light logs a warning instead."""
        light = self._lights[name]
        if await light.binary.get_value():
            self.logger.warning(f"{name!r} is a binary light source; intensity ignored")
            return
        await asyncio.wait_for(light.intensity.set(intensity), timeout=self._timeout)

    def shutdown(self) -> None:
        """Shut down every light device that supports it."""
        for light in self._lights.values():
            if isinstance(light, HasAsyncShutdown):
                run_coro(light.shutdown())
