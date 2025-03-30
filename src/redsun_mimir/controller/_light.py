from __future__ import annotations

from typing import TYPE_CHECKING

from sunflare.log import Loggable

from ..protocols import LightProtocol

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sunflare.model import ModelProtocol
    from sunflare.virtual import VirtualBus

    from ._config import LightControllerInfo


class LightController(Loggable):
    """Controller for the light model.

    Parameters
    ----------
    config : ``LightControllerInfo``
        Configuration for the light controller.
    models : ``Mapping[str, ModelProtocol]``
        Mapping of model names to model instances.
    bus : ``VirtualBus``
        The bus for communication.

    """

    def __init__(
        self,
        ctrl_info: LightControllerInfo,
        models: Mapping[str, ModelProtocol],
        virtual_bus: VirtualBus,
    ) -> None:
        self._ctrl_info = ctrl_info
        self._virtual_bus = virtual_bus

        self._lights = {
            name: model
            for name, model in models.items()
            if isinstance(model, LightProtocol)
        }

    def registration_phase(self) -> None:
        """Register the controller."""
        self._virtual_bus.register_signals(self)

    def connection_phase(self) -> None:
        """Connect the controller."""
        self._virtual_bus["LightWidget"]["sigToggleLightRequest"].connect(self.trigger)
        self._virtual_bus["LightWidget"]["sigIntensityRequest"].connect(self.set)
        self.logger.debug("Connected to LightWidget")

    def trigger(self, name: str) -> None:
        """Toggle the light.

        Parameters
        ----------
        name : ``str``
            Name of the light.

        """
        s = self._lights[name].trigger()
        try:
            s.wait(self._ctrl_info.timeout)
        except Exception as e:
            self.logger.error(f"Failed toggle on {name}: {e}")
        else:
            self.logger.debug(
                f"Toggled source {name} {not self._lights[name].enabled} -> {self._lights[name].enabled}"
            )

    def set(self, name: str, intensity: float) -> None:
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
            s.wait(self._ctrl_info.timeout)
        except Exception:
            self.logger.exception(
                f"Timeout when setting {name} at {intensity} {light.model_info.egu}"
            )
