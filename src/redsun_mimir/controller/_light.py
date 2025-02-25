from __future__ import annotations

from typing import TYPE_CHECKING, Mapping

from bluesky.protocols import Reading
from sunflare.log import Loggable
from sunflare.virtual import Signal

from ..protocols import LightProtocol

if TYPE_CHECKING:
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

    Attributes
    ----------
    sigNewIntensity : ``Signal[str, dict[str, Reading[float]]]``
        Signal emitted when a new intensity is set.
        - ``str``: light name
        - ``dict[str, Reading[float]]``: new intensity

    """

    sigNewIntensity = Signal(str, Reading[float])

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
        ...

    def set_intensity(self, name: str, intensity: float) -> None:
        """Set the intensity of the light.

        When the intensity is set, the controller will emit
        the ``sigNewIntensity`` signal to notify the widget
        of the new intensity.

        Parameters
        ----------
        name : ``str``
            Name of the light.
        intensity : ``float``
            Intensity to set.

        """
        s = self._lights[name].set(intensity)
        try:
            s.wait(self._ctrl_info.timeout)
        except Exception as e:
            self.exception(f"Failed set intensity on {name}: {e}")
        self.sigNewIntensity.emit(name, self._lights[name].read()[name])
