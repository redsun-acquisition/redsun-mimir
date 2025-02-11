from __future__ import annotations

from typing import TYPE_CHECKING

from sunflare.view.qt import BaseQtWidget
from sunflare.virtual import Signal

if TYPE_CHECKING:
    from typing import Any

    from bluesky.protocols import Reading
    from event_model.documents.event_descriptor import DataKey
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
    sigGetDescription = Signal()

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
        self._description: dict[str, dict[str, DataKey]] = {}
        self._configuration: dict[str, dict[str, Reading]] = {}

    def registration_phase(self) -> None:
        """Register your signals to the virtual bus."""
        self._virtual_bus.register_signals(self)

    def connection_phase(self) -> None:
        """Connect your signals to the virtual bus.

        The controller layer will be already built when this method is called.
        We use it to directly build the GUI by retrieving a configuration of
        the currently allocated motors to create the proper widget layout.
        """
        self._virtual_bus["StageController"]["sigNewPosition"].connect(
            self._update_position
        )
        self._virtual_bus["StageController"]["sigMotorDescription"].connect(
            self._update_description
        )
        self._virtual_bus["StageController"]["sigMotorConfiguration"].connect(
            self._update_configuration
        )
        self.sigGetDescription.emit()
        # we have the configuration,
        # we can build the GUI now
        self._build_gui()

    def _update_position(self, motor: str, position: float) -> None:
        """Update the motor position."""
        # TODO: implement
        ...

    def _update_description(self, description: dict[str, dict[str, DataKey]]) -> None:
        """Update the motor description."""
        self._description = description

    def _update_configuration(
        self, configuration: dict[str, dict[str, Reading]]
    ) -> None:
        """Update the motor configuration."""
        self._configuration = configuration

    def _build_gui(self) -> None:
        """Build the GUI."""
        ...
