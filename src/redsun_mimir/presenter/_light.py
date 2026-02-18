from __future__ import annotations

from typing import TYPE_CHECKING

from dependency_injector import providers
from sunflare.log import Loggable
from sunflare.virtual import IsProvider, VirtualAware

from redsun_mimir.protocols import LightProtocol  # noqa: TC001

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    from bluesky.protocols import Descriptor, Reading
    from dependency_injector.containers import DynamicContainer
    from sunflare.device import Device
    from sunflare.virtual import VirtualBus


class LightPresenter(Loggable, IsProvider, VirtualAware):
    """Presenter for light source control.

    Forwards toggle and intensity requests from
    [`LightView`][redsun_mimir.view.LightView] to the underlying
    light devices.

    Parameters
    ----------
    devices :
        Mapping of device names to device instances.
    virtual_bus :
        The virtual bus for signal exchange.
    **kwargs :
        Additional keyword arguments.

        - `timeout` (`float | None`): Status wait timeout in seconds.
    """

    def __init__(
        self,
        devices: Mapping[str, Device],
        virtual_bus: VirtualBus,
        /,
        **kwargs: Any,
    ) -> None:
        self._timeout: float | None = kwargs.get("timeout", None)
        self.virtual_bus = virtual_bus
        self.devices = devices

        self._lights = {
            name: model
            for name, model in devices.items()
            if isinstance(model, LightProtocol)
        }

        self.virtual_bus.register_signals(self)

    def models_configuration(self) -> dict[str, dict[str, Reading[Any]]]:
        """Get the current configuration readings of all light devices.

        Returns
        -------
        dict[str, dict[str, Reading[Any]]]
            Mapping of light names to their current configuration readings.
        """
        return {
            name: light.read_configuration() for name, light in self._lights.items()
        }

    def models_description(self) -> dict[str, dict[str, Descriptor]]:
        """Get the configuration descriptors of all light devices.

        Returns
        -------
        dict[str, dict[str, Descriptor]]
            Mapping of light names to their configuration descriptors.
        """
        return {
            name: light.describe_configuration() for name, light in self._lights.items()
        }

    def register_providers(self, container: DynamicContainer) -> None:
        """Register light model info as a provider in the DI container."""
        container.light_configuration = providers.Object(self.models_configuration())
        container.light_description = providers.Object(self.models_description())

    def connect_to_virtual(self) -> None:
        """Connect to the virtual bus signals."""
        self.virtual_bus.signals["LightView"]["sigToggleLightRequest"].connect(
            self.trigger
        )
        self.virtual_bus.signals["LightView"]["sigIntensityRequest"].connect(self.set)

    def trigger(self, name: str) -> None:
        """Toggle the light.

        Parameters
        ----------
        name : ``str``
            Name of the light.

        """
        s = self._lights[name].trigger()
        try:
            s.wait(self._timeout)
        except Exception as e:
            self.logger.error(f"Failed toggle on {name}: {e}")
        else:
            self.logger.debug(
                f"Toggled source {name} {not self._lights[name].enabled} -> {self._lights[name].enabled}"
            )

    def set(self, name: str, intensity: int | float) -> None:
        """Set the intensity of the light.

        Parameters
        ----------
        name : ``str``
            Name of the light.
        intensity : ``float``
            Intensity to set.

        """
        light = self._lights[name]
        s = light.set(intensity)
        try:
            s.wait(self._timeout)
        except Exception:
            self.logger.exception(f"Timeout when setting {name} at {intensity}")
