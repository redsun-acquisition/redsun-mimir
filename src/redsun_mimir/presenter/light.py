from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from redsun import DevicesOf, slot
from redsun.aio import run_coro
from redsun.log import Loggable

from redsun_mimir.protocols import LightProtocol  # noqa: TC001

if TYPE_CHECKING:
    from typing import Any

    from bluesky.protocols import Descriptor, Reading


class LightPresenter(Loggable):
    """Presenter for light source control.

    Forwards toggle and intensity requests from
    [`LightView`][redsun_mimir.view.LightView] to the light devices.

    Parameters
    ----------
    timeout
        Status wait timeout in seconds; `None` means `2.0`.
    """

    def __init__(
        self,
        name: str,
        *,
        lights: DevicesOf[LightProtocol],
        timeout: float | None = None,
    ) -> None:
        self.name = name
        self._timeout: float = timeout or 2.0

        self._lights = lights
        self._locks = {name: asyncio.Lock() for name in self._lights}
        if not self._lights:
            self.logger.warning("No device found.")
        else:
            names = ", ".join(light.name for light in self._lights.values())
            self.logger.debug(f"Found devices: {names}")

    def light_readings(self) -> dict[str, Reading[Any]]:
        """Return every light's configuration and current readings, by data key."""
        result: dict[str, Reading[Any]] = {}
        for light in self._lights.values():
            result.update(run_coro(light.read_configuration()))
            result.update(run_coro(light.read()))
        return result

    def light_descriptors(self) -> dict[str, Descriptor]:
        """Return every light's configuration and reading descriptors, by data key."""
        result: dict[str, Descriptor] = {}
        for light in self._lights.values():
            result.update(run_coro(light.describe_configuration()))
            result.update(run_coro(light.describe()))
        return result

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
