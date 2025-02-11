from __future__ import annotations

from typing import TYPE_CHECKING

from sunflare.view.qt import BaseQtWidget
from sunflare.virtual import Signal

if TYPE_CHECKING:
    from typing import Any

    from sunflare.config import RedSunSessionInfo
    from sunflare.virtual import VirtualBus


class StageWidget(BaseQtWidget):
    """Stage widget for Redsun Mimir.

    Parameters
    ----------
    config : RedSunSessionInfo
        Configuration for the session.
    virtual_bus : VirtualBus
        Virtual bus for the session.

    Attributes
    ----------
    sigMotorMove : Signal[str, str, float]
        Signal emitted when a stage is moved.
        - str: stage name
        - float: stage new position

    """

    sigMotorMove = Signal(str, float)

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
        self._virtual_bus.register_signals(self)

    def connection_phase(self) -> None:
        """Connect your signals to the virtual bus."""
        self._virtual_bus["StageController"]["sigNewPosition"].connect(
            self._update_position
        )

    def _update_position(self, stage: str, position: float) -> None:
        """Update the stage position."""
        # TODO: implement
        ...
