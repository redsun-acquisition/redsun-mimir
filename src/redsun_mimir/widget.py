from __future__ import annotations

from typing import TYPE_CHECKING

from sunflare.view.qt import BaseQtWidget

if TYPE_CHECKING:
    from typing import Any

    from sunflare.config import RedSunSessionInfo
    from sunflare.virtual import VirtualBus


class StageWidget(BaseQtWidget):
    """Stage widget for RedSun Mimir."""

    def __init__(
        self,
        config: RedSunSessionInfo,
        virtual_bus: VirtualBus,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._config = config
        self._virtual_bus = virtual_bus

    def registration_phase(self) -> None:
        """Register your signals to the virtual bus."""

    def connection_phase(self) -> None:
        """Connect your signals to the virtual bus."""
