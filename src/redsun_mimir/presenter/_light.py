from __future__ import annotations

from typing import TYPE_CHECKING

from dependency_injector import providers
from sunflare.log import Loggable
from sunflare.presenter import Presenter
from sunflare.virtual import IsInjectable, IsProvider

from redsun_mimir.protocols import LightProtocol  # noqa: TC001

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    from bluesky.protocols import Descriptor, Reading
    from sunflare.device import Device
    from sunflare.virtual import VirtualContainer


class LightPresenter(Presenter, Loggable, IsProvider, IsInjectable):
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
    **kwargs :
        Additional keyword arguments.

        - `timeout` (`float | None`): Status wait timeout in seconds.
    """

    def __init__(
        self,
        name: str,
        devices: Mapping[str, Device],
        /,
        **kwargs: Any,
    ) -> None:
        super().__init__(name, devices)
        self._timeout: float | None = kwargs.get("timeout", 5.0)

        self._lights = {
            name: model
            for name, model in devices.items()
            if isinstance(model, LightProtocol)
        }

    def models_configuration(self) -> dict[str, Reading[Any]]:
        r"""Get the current configuration readings of all light devices.

        Returns a flat dict keyed by the canonical ``prefix:name-property``
        scheme, merging all lights together (matching the detector pattern).

        Returns
        -------
        dict[str, Reading[Any]]
            Flat mapping of canonical keys to their current readings.
        """
        result: dict[str, Reading[Any]] = {}
        for light in self._lights.values():
            result.update(light.read_configuration())
        return result

    def models_description(self) -> dict[str, Descriptor]:
        r"""Get the configuration descriptors of all light devices.

        Returns a flat dict keyed by the canonical ``prefix:name-property``
        scheme, merging all lights together (matching the detector pattern).

        Returns
        -------
        dict[str, Descriptor]
            Flat mapping of canonical keys to their descriptors.
        """
        result: dict[str, Descriptor] = {}
        for light in self._lights.values():
            result.update(light.describe_configuration())
        return result

    def register_providers(self, container: VirtualContainer) -> None:
        """Register light model info as a provider in the DI container."""
        container.light_configuration = providers.Object(self.models_configuration())
        container.light_description = providers.Object(self.models_description())
        container.register_signals(self)

    def inject_dependencies(self, container: VirtualContainer) -> None:
        """Connect to the virtual container signals."""
        container.signals["LightView"]["sigToggleLightRequest"].connect(self.trigger)
        container.signals["LightView"]["sigIntensityRequest"].connect(self.set)

    def _bare_name(self, device_label: str) -> str:
        """Resolve a device label to the bare device name used as dict key.

        Returns the label unchanged since devices are now keyed by bare name only.

        Parameters
        ----------
        device_label :
            Device name.
        """
        return device_label

    def trigger(self, name: str) -> None:
        """Toggle the light.

        Parameters
        ----------
        name : ``str``
            Name of the light.

        """
        s = self._lights[self._bare_name(name)].trigger()
        try:
            s.wait(self._timeout)
        except Exception as e:
            self.logger.error(f"Failed toggle on {name}: {e}")
        else:
            light = self._lights[self._bare_name(name)]
            self.logger.debug(
                f"Toggled source {name} {not light.enabled} -> {light.enabled}"
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
        light = self._lights[self._bare_name(name)]
        s = light.set(intensity)
        try:
            s.wait(self._timeout)
        except Exception:
            self.logger.exception(f"Timeout when setting {name} at {intensity}")
