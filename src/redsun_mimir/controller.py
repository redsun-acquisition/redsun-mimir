from __future__ import annotations

from threading import Thread
from typing import TYPE_CHECKING, Any, Mapping, Optional, Callable
from queue import Queue

from sunflare.log import Loggable
from sunflare.virtual import Signal, VirtualBus

from ._protocols import MotorProtocol

from event_model.documents.event_descriptor import DataKey
from bluesky.protocols import Reading

if TYPE_CHECKING:
    from sunflare.model import ModelProtocol
    from functools import partial

    from bluesky.utils import MsgGenerator

    from .config import StageControllerInfo


class DaemonLoop(Thread):
    """A subclass of ``threading.Thread`` which runs a persistent daemon loop.

    The daemon will continously inspect a queue of tasks to execute.
    Whenever a task is available (a new position is requested),
    the daemon will execute it in the background.

    Parameters
    ----------
    queue : ``Queue[Optional[tuple[str, float]]]``
        Queue of new motor positions.
    motors : ``dict[str, MotorProtocol]``
        Mapping of motor names to motor instances.
    exception_cb : ``Callable[[str], None]``
        Callback to handle exceptions. This should be
        mapped to the main controller ``exception`` method.

    Attributes
    ----------
    sigNewPosition : Signal[str, float]
        Signal emitted when a new position is set.
        Forwards the response to the controller which will
        emit the same signal to the widget.
        - ``str``: motor name
        - ``float``: new position

    """

    sigNewPosition = Signal(str, float)

    def __init__(
        self,
        queue: Queue[Optional[tuple[str, float]]],
        motors: dict[str, MotorProtocol],
        exception_cb: Callable[[str], None],
    ) -> None:
        super().__init__(daemon=True)
        self._queue = queue
        self._running = False
        self._motors = motors
        self._exception_cb = exception_cb

    def run(self) -> None:
        """Run the daemon loop."""
        self._running = True
        while self._running:
            # block until a task is available
            task = self._queue.get()
            if task is not None:
                motor, position = task
                self._do_move(self._motors[motor], position)
                self._queue.task_done()
            else:
                # Stop the daemon
                self._running = False

    def _do_move(self, motor: MotorProtocol, position: float) -> None:
        """Move a motor to a given position.

        Wait on the status object to complete in a background thread.
        """
        s = motor.set(position)
        try:
            s.wait()
        except Exception as e:
            self._exception_cb(f"Failed to move {motor.name} to {position}: {e}")
        else:
            self.sigNewPosition.emit(motor, position)


class StageController(Loggable):
    """Motor stage controller for RedSun Mimir.

    The controller allows manual setting of stage positions;
    communication with the user interface is done via
    signals exchanged with the ``StageWidget`` accross
    the virtual bus.

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
    sigMotorDescription : ``Signal[str, dict[str, DataKey]]``
        Signal emitted when the motor configuration is described.
        - ``str``: motor name
        - ``dict[str, DataKey]``: motor configuration description
    sigMotorConfiguration : ``Signal[str, dict[str, Reading]]``
        Signal emitted when the motor configuration is read.
        - ``str``: motor name
        - ``dict[str, Reading]``: motor configuration

    """

    sigNewPosition = Signal(str, float)
    sigMotorDescription = Signal(str, dict[str, DataKey])
    sigMotorConfiguration = Signal(str, dict[str, Reading])

    def __init__(
        self,
        ctrl_info: StageControllerInfo,
        models: Mapping[str, ModelProtocol],
        virtual_bus: VirtualBus,
    ) -> None:
        self._ctrl_info = ctrl_info
        self._virtual_bus = virtual_bus
        self._plans: list[partial[MsgGenerator[Any]]] = []
        self._queue: Queue[Optional[tuple[str, float]]] = Queue()

        self._motors = {
            name: model
            for name, model in models.items()
            if isinstance(model, MotorProtocol)
        }

        self._daemon = DaemonLoop(self._queue, self._motors, self.exception)
        self._daemon.sigNewPosition.connect(self.sigNewPosition.emit)

    def move(self, motor: str, position: float) -> None:
        """Move a motor to a given position.

        Sends a new position to the daemon queue.
        """
        self._queue.put((motor, position))

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
