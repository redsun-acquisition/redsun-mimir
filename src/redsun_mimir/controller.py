from __future__ import annotations

from typing import Mapping, TYPE_CHECKING, Any
from functools import partial

from sunflare.model import ModelProtocol
from sunflare.virtual import VirtualBus

from bluesky.utils import MsgGenerator

if TYPE_CHECKING:
    from .config import StageControllerInfo


class StageController:
    """Motor stage controller for RedSun Mimir."""

    def __init__(
        self,
        ctrl_info: StageControllerInfo,
        models: Mapping[str, ModelProtocol],
        virtual_bus: VirtualBus,
    ) -> None:
        self._ctrl_info = ctrl_info
        self._virtual_bus = virtual_bus
        self._plans: list[partial[MsgGenerator[Any]]] = []

        # you should select which models
        # to memorize by defining your
        # custom Python protocol
        self._models = models

    def shutdown(self) -> None:
        """Shutdown the controller.

        Free any allocated resource.
        If no resource is kept in the controller,
        leave empty.
        """
        ...

    def registration_phase(self) -> None:
        """Register the controller signals to the virtual bus."""
        ...

    def connection_phase(self) -> None:
        """Connect to other controllers/widgets in the active session."""
        ...

    @property
    def controller_info(self) -> StageControllerInfo:
        """Controller information container."""
        return self._ctrl_info

    @property
    def plans(self) -> list[partial[MsgGenerator[Any]]]:
        """List of available plans."""
        return self._plans
