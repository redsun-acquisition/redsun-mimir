from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any, Mapping

from sunflare.log import Loggable
from sunflare.virtual import Signal, VirtualBus

from ._protocols import MotorProtocol

if TYPE_CHECKING:
    from sunflare.model import ModelProtocol
    from functools import partial

    from bluesky.utils import MsgGenerator

    from .config import StageControllerInfo


class StageController(Loggable):
    """Motor stage controller for RedSun Mimir.

    The controller allows manual setting of stage positions.

    Whenever a new position is requested from ``StageWidget``
    via the ``sigMotorMove`` signal, the controller will move the stage
    to the requested position by launching a background thread
    which will call the ``set`` method of the corresponding motor model.

    When the movement is completed, the controller will emit
    the ``sigMotorMoved`` signal to notify the widget.

    Parameters
    ----------
    ctrl_info : ``StageControllerInfo``
        Configuration for the stage controller.
    models : ``Mapping[str, ModelProtocol]``
        Mapping of model names to model instances.
    virtual_bus : VirtualBus
        Virtual bus for the session.

    Attributes
    ----------
    sigNewPosition : ``Signal[str, float]``
        Signal emitted when a new position is set.
        - ``str``: motor name
        - ``float``: new position

    """

    sigNewPosition = Signal(str, float)

    def __init__(
        self,
        ctrl_info: StageControllerInfo,
        models: Mapping[str, ModelProtocol],
        virtual_bus: VirtualBus,
    ) -> None:
        self._ctrl_info = ctrl_info
        self._virtual_bus = virtual_bus
        self._plans: list[partial[MsgGenerator[Any]]] = []
        self._pool = ThreadPoolExecutor(thread_name_prefix="StageController")

        self._motors = {
            name: model
            for name, model in models.items()
            if isinstance(model, MotorProtocol)
        }

    def move(self, motor: str, position: float) -> None:
        """Move a motor to a given position."""
        self._pool.submit(self._do_move, self._motors[motor], position)

    def _do_move(self, motor: MotorProtocol, position: float) -> None:
        """Move a motor to a given position.

        Wait on the status object to complete in a background thread.
        """
        s = motor.set(position)
        try:
            s.wait()
        except Exception as e:
            self.exception(f"Failed to move {motor.name} to {position}: {e}")
        self.sigNewPosition.emit(motor, position)

    def shutdown(self) -> None:
        """Shutdown the controller.

        Free any allocated resource.
        If no resource is kept in the controller,
        leave empty.
        """
        ...

    def registration_phase(self) -> None:
        """Register the controller signals to the virtual bus."""
        self._virtual_bus.register_signals(self)

    def connection_phase(self) -> None:
        """Connect to other controllers/widgets in the active session."""
        self._virtual_bus["StageWidget"]["sigMotorMove"].connect(self.move)

    @property
    def controller_info(self) -> StageControllerInfo:
        """Controller information container."""
        return self._ctrl_info

    @property
    def plans(self) -> list[partial[MsgGenerator[Any]]]:
        """List of available plans."""
        return self._plans
