from __future__ import annotations

from typing import TYPE_CHECKING

from dependency_injector import providers
from sunflare.log import Loggable
from sunflare.virtual import VirtualAware

from redsun_mimir.protocols import LightProtocol  # noqa: TC001

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    from dependency_injector.containers import DynamicContainer
    from sunflare.device import Device
    from sunflare.virtual import VirtualBus


class LightController(Loggable, VirtualAware):
    """Controller for the light model.

    Parameters
    ----------
    devices : ``Mapping[str, Device]``
        Mapping of device names to device instances.
    virtual_bus : ``VirtualBus``
        The bus for communication.
    **kwargs : Any
        Additional keyword arguments.
        - ``timeout`` (float | None): Timeout in seconds.

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

    def models_info(self) -> dict[str, LightProtocol]:
        """Get the light devices.

        Returns
        -------
        dict[str, LightProtocol]
            Mapping of light names to light device instances.
        """
        return dict(self._lights)

    def register_providers(self, container: DynamicContainer) -> None:
        """Register light model info as a provider in the DI container."""
        container.light_models = providers.Object(self.models_info())  # type: ignore[attr-defined]
        self.virtual_bus.register_signals(self)

    def connect_to_virtual(self) -> None:
        """Connect to the virtual bus signals."""
        self.virtual_bus.signals["LightWidget"]["sigToggleLightRequest"].connect(
            self.trigger
        )
        self.virtual_bus.signals["LightWidget"]["sigIntensityRequest"].connect(
            self.set
        )

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
            self.logger.exception(
                f"Timeout when setting {name} at {intensity} {light.egu}"
            )
