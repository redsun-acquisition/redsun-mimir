from __future__ import annotations

from typing import TYPE_CHECKING, TypeGuard

from sunflare.log import Loggable

from ..protocols import ResizableProtocol

if TYPE_CHECKING:
    from typing import Mapping

    from sunflare.model import ModelProtocol
    from sunflare.virtual import VirtualBus

    from ._config import ImageControllerInfo


def is_resizable(
    item: tuple[str, ModelProtocol],
) -> TypeGuard[tuple[str, ResizableProtocol]]:
    return isinstance(item[1], ResizableProtocol)


class ImageController(Loggable):
    def __init__(
        self,
        ctrl_info: ImageControllerInfo,
        models: Mapping[str, ModelProtocol],
        virtual_bus: VirtualBus,
    ) -> None:
        self.ctrl_info = ctrl_info
        self.virtual_bus = virtual_bus
        self.models = dict(filter(is_resizable, models.items()))

    def registration_phase(self) -> None:
        """Register the models with the virtual bus."""
        ...

    def connection_phase(self) -> None:
        """Connect the models to the virtual bus."""
        ...
