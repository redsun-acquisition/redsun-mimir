from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from dependency_injector import providers
from redsun.engine import get_shared_loop
from redsun.log import Loggable
from redsun.presenter import Presenter
from redsun.utils import find_signals
from redsun.virtual import HasShutdown

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
        **_: Any,
    ) -> None:
        super().__init__(name, devices)
        self._timeout: float = timeout or 2.0

        self._lights = {
            dev_name: model
            for dev_name, model in devices.items()
            if isinstance(model, LightProtocol)
        }
        if not self._lights:
            self.logger.warning("No light devices found.")
        else:
            self.logger.debug(f"Found light devices: {list(self._lights)}")

    def models_configuration(self) -> dict[str, Reading[Any]]:
        r"""Get the current configuration readings of all light devices.

        Returns a flat dict keyed by the canonical ``prefix:name-property``
        scheme, merging all lights together.

        Returns
        -------
        dict[str, Reading[Any]]
            Flat mapping of canonical keys to their current readings.
        """
        loop = get_shared_loop()
        result: dict[str, Reading[Any]] = {}
        for light in self._lights.values():
            result.update(
                asyncio.run_coroutine_threadsafe(
                    light.read_configuration(), loop
                ).result()
            )
        return result

    def models_description(self) -> dict[str, Descriptor]:
        r"""Get the configuration descriptors of all light devices.

        Returns a flat dict keyed by the canonical ``prefix:name-property``
        scheme, merging all lights together.

        Returns
        -------
        dict[str, Descriptor]
            Flat mapping of canonical keys to their descriptors.
        """
        loop = get_shared_loop()
        result: dict[str, Descriptor] = {}
        for light in self._lights.values():
            result.update(
                asyncio.run_coroutine_threadsafe(
                    light.describe_configuration(), loop
                ).result()
            )
        return result

    def register_providers(self, container: VirtualContainer) -> None:
        """Register light model info as a provider in the DI container."""
        container.light_configuration = providers.Object(self.models_configuration())
        container.light_description = providers.Object(self.models_description())
        container.register_signals(self)

    def inject_dependencies(self, container: VirtualContainer) -> None:
        """Connect to the virtual container signals."""
        sigs = find_signals(container, ["sigToggleLightRequest", "sigIntensityRequest"])
        if "sigToggleLightRequest" in sigs:
            sigs["sigToggleLightRequest"].connect(self.trigger)
        if "sigIntensityRequest" in sigs:
            sigs["sigIntensityRequest"].connect(self.set)

    def trigger(self, name: str) -> None:
        """Toggle the light on or off.

        Parameters
        ----------
        name :
            Name of the light device.
        """
        loop = get_shared_loop()
        future = asyncio.run_coroutine_threadsafe(self._trigger(name), loop)
        try:
            future.result(timeout=self._timeout)
        except Exception:
            self.logger.exception(f"Failed toggle on {name!r}")

    async def _trigger(self, name: str) -> None:
        light = self._lights[name]
        await asyncio.wait_for(light.trigger(), timeout=self._timeout)
        state = await light.enabled.get_value()
        self.logger.debug(f"Toggled {name!r} → enabled={state}")

    def set(self, name: str, intensity: int | float) -> None:
        """Set the intensity of a light source.

        Parameters
        ----------
        name :
            Name of the light device.
        intensity :
            New intensity value.
        """
        loop = get_shared_loop()
        future = asyncio.run_coroutine_threadsafe(self._set(name, intensity), loop)
        try:
            future.result(timeout=self._timeout)
        except Exception:
            self.logger.exception(f"Timeout when setting {name!r} to {intensity}")

    async def _set(self, name: str, intensity: int | float) -> None:
        light = self._lights[name]
        await asyncio.wait_for(light.intensity.set(intensity), timeout=self._timeout)

    def shutdown(self) -> None:
        """Shutdown the presenter and all light devices."""
        for light in self._lights.values():
            if isinstance(light, HasShutdown):
                light.shutdown()
