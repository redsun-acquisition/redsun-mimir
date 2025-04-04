from __future__ import annotations

from typing import TYPE_CHECKING

from sunflare.log import Loggable
from sunflare.virtual import Signal

from ..protocols import ResizableProtocol

if TYPE_CHECKING:
    from typing import Mapping

    from sunflare.model import ModelProtocol
    from sunflare.virtual import VirtualBus

    from ..protocols import ROI
    from ._config import ImageControllerInfo


class ImageController(Loggable):
    sigNewConfiguration = Signal(str, object)

    def __init__(
        self,
        ctrl_info: ImageControllerInfo,
        models: Mapping[str, ModelProtocol],
        virtual_bus: VirtualBus,
    ) -> None:
        self.ctrl_info = ctrl_info
        self.virtual_bus = virtual_bus
        self.models = {
            name: model
            for name, model in models.items()
            if isinstance(model, ResizableProtocol)
        }

    def configure(self, model: str, config: ROI) -> None:
        """Configure a model region of interest.

        Calls the ``resize`` method of the model providing the new ROI.

        Emits ``sigNewConfiguration`` signal when successful,
        with the detector name and the new ROI.

        Parameters
        ----------
        model : ``str``
            Detector name.
        config : ``ROI``
            New ROI configuration.

        """
        self.logger.debug(f"Resizing '{model}' to {config}")
        s = self.models[model].resize(config)
        try:
            s.wait(self.ctrl_info.timeout)
        finally:
            if not s.success:
                self.logger.error(f"Failed to resize '{model}': {s.exception()}")
            else:
                self.sigNewConfiguration.emit(model, config)

    def registration_phase(self) -> None:
        """Register the models with the virtual bus."""
        self.virtual_bus.register_signals(self)

    def connection_phase(self) -> None:
        """Connect the models to the virtual bus."""
        ...
