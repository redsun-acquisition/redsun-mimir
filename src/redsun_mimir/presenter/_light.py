from __future__ import annotations

from typing import TYPE_CHECKING

import in_n_out as ino
from sunflare.log import Loggable

from redsun_mimir.device import LightModelInfo
from redsun_mimir.protocols import LightProtocol  # noqa: TC001

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sunflare.model import PModel
    from sunflare.virtual import VirtualBus

    from ._config import LightControllerInfo

store = ino.Store.create("LightModelInfo")


class LightController(Loggable):
    """Controller for the light model.

    Parameters
    ----------
    config : ``LightControllerInfo``
        Configuration for the light presenter.
    models : ``Mapping[str, PModel]``
        Mapping of model names to model instances.
    bus : ``VirtualBus``
        The bus for communication.

    """

    def __init__(
        self,
        ctrl_info: LightControllerInfo,
        models: Mapping[str, PModel],
        virtual_bus: VirtualBus,
    ) -> None:
        self._ctrl_info = ctrl_info
        self._virtual_bus = virtual_bus

        self._lights = {
            name: model
            for name, model in models.items()
            if isinstance(model, LightProtocol)
        }

        store.register_provider(self.models_info, type_hint=dict[str, LightModelInfo])

    def models_info(self) -> dict[str, LightModelInfo]:
        """Get the models information.

        Returns
        -------
        dict[str, LightModelInfo]
            Mapping of model names to model information.
        """
        return {name: model.model_info for name, model in self._lights.items()}

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
            s.wait(self._ctrl_info.timeout)
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
            s.wait(self._ctrl_info.timeout)
        except Exception:
            self.logger.exception(
                f"Timeout when setting {name} at {intensity} {light.model_info.egu}"
            )
