from __future__ import annotations

from typing import TYPE_CHECKING

import in_n_out as ino
from sunflare.log import Loggable

from redsun_mimir.protocols import LightProtocol  # noqa: TC001

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    from sunflare.device import Device
    from sunflare.virtual import VirtualBus

store = ino.Store.create("LightModelInfo")


class LightController(Loggable):
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
        self._virtual_bus = virtual_bus

        self._lights = {
            name: model
            for name, model in devices.items()
            if isinstance(model, LightProtocol)
        }

        store.register_provider(self.models_info, type_hint=dict[str, LightProtocol])

    def models_info(self) -> dict[str, LightProtocol]:
        """Get the light devices.

        Returns
        -------
        dict[str, LightProtocol]
            Mapping of light names to light device instances.
        """
        return dict(self._lights)

    def registration_phase(self) -> None:
        """Register the presenter."""
        self._virtual_bus.register_signals(self)

    def connection_phase(self) -> None:
        """Connect the presenter."""
        self._virtual_bus.signals["LightWidget"]["sigToggleLightRequest"].connect(
            self.trigger
        )
        self._virtual_bus.signals["LightWidget"]["sigIntensityRequest"].connect(
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
