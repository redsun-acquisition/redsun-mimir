from __future__ import annotations

from queue import Queue
from threading import Thread
from typing import TYPE_CHECKING

from sunflare.log import Loggable
from sunflare.virtual import Signal, VirtualBus

from ..protocols import MotorProtocol

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    from sunflare.model import ModelProtocol

    from redsun_mimir.controller import StageControllerInfo


class StageController(Loggable):
    """Motor stage controller for Redsun Mimir.

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
    sigNewPosition : ``Signal[str, str, float]``
        Signal emitted when a new position is set.
        - ``str``: motor name
        - ``str``: motor axis
        - ``float``: new position
    sigNewConfiguration : ``Signal[str, dict[str, bool]]``
        Signal emitted when a configuration value is changed.
        - ``str``: motor name
        - ``dict[str, bool]``: mapping of configuration parameters to success status

    Notes
    -----
    ``sigNewPosition`` is emitted from a background thread;
    when connecting to a slot, ensure that the callback
    is invoked in the main thread as follows:

    .. code-block:: python

        class MyReceiver:
            def on_new_position(self, motor: str, position: float) -> None:
                # do something with the new position
                ...

            def connection_phase(self) -> None:
                # connect the signal to the slot;
                # the slot will be invoked in the main thread
                self._virtual_bus["StageController"]["sigNewPosition"].connect(
                    self.on_new_position, thread="main"
                )

    """

    sigNewPosition = Signal(str, str, float)
    sigNewConfiguration = Signal(str, dict[str, bool])

    def __init__(
        self,
        ctrl_info: StageControllerInfo,
        models: Mapping[str, ModelProtocol],
        virtual_bus: VirtualBus,
    ) -> None:
        self._ctrl_info = ctrl_info
        self._virtual_bus = virtual_bus
        self._queue: Queue[tuple[str, str, float] | None] = Queue()

        self._motors = {
            name: model
            for name, model in models.items()
            if isinstance(model, MotorProtocol)
        }

        self._daemon = Thread(target=self._run_loop, daemon=True)
        self._daemon.start()

        self.logger.info("Stage controller initialized")

    def move(self, motor: str, axis: str, position: float) -> None:
        """Move a motor to a given position.

        Sends a new position to the daemon queue.
        """
        self._queue.put((motor, axis, position))

    def configure(self, motor: str, config: dict[str, Any]) -> dict[str, bool]:
        """Configure a motor.

        Update one or more configuration parameters of a motor.

        Emits the ``sigNewConfiguration`` signal when the configuration
        is completed, returning a mapping of configuration parameters
        to success status.

        Parameters
        ----------
        motor : ``str``
            Motor name.
        config : ``dict[str, Any]``
            Mapping of configuration parameters to new values.

        Returns
        -------
        ``dict[str, bool]``
            Mapping of configuration parameters to success status.

        """
        success_map: dict[str, bool] = {}
        for key, value in config.items():
            self.logger.debug(f"Configuring {key} of {motor} to {value}")
            s = self._motors[motor].set(value, prop=key)
            try:
                s.wait(self._ctrl_info.timeout)
            except Exception as e:
                self.logger.exception(f"Failed to configure {key} of {motor}: {e}")
            finally:
                if not s.success:
                    self.logger.error(
                        f"Failed to configure {key} of {motor}: {s.exception()}"
                    )
                success_map[key] = s.success
        self.sigNewConfiguration.emit(motor, success_map)
        return success_map

    def shutdown(self) -> None:
        """Shutdown the controller.

        Close the daemon thread and wait
        for it to finish its last task
        """
        self._queue.put(None)
        self._queue.join()

    def registration_phase(self) -> None:
        """Register the controller signals to the virtual bus."""
        self._virtual_bus.register_signals(self)

    def connection_phase(self) -> None:
        """Connect to other controllers/views in the active session."""
        self._virtual_bus["StageWidget"]["sigMotorMove"].connect(self.move)
        self._virtual_bus["StageWidget"]["sigConfigChanged"].connect(self.configure)

    def _run_loop(self) -> None:
        while True:
            # block until a task is available
            task = self._queue.get()
            if task is not None:
                motor, axis, position = task
                self.logger.debug(f"Moving {motor} to {position} on {axis}")
                self._do_move(self._motors[motor], axis, position)
                self._queue.task_done()
            else:
                # ensure no pending task
                self._queue.task_done()
                break

    def _do_move(self, motor: MotorProtocol, axis: str, position: float) -> None:
        """Move a motor to a given position.

        Wait on the status object to complete in a background thread.
        When the movement is completed, emit the ``sigNewPosition`` signal.

        Parameters
        ----------
        motor : ``MotorProtocol``
            Motor instance to move.
        axis : ``str``
            Axis to move.
        position : ``float``
            New position to set.

        Notes
        -----
        ``sigNewPosition`` is emitted from a background thread;
        users need to ensure that any connected callback is invoked
        in the main thread; see the class docstring for an example.

        """
        if axis != motor.axis:
            ret = self.configure(motor.name, {"axis": axis})
            if not ret:
                return
        s = motor.set(position)
        try:
            s.wait(self._ctrl_info.timeout)
        except Exception as e:
            self.logger.exception(f"Failed to move {motor.name} to {position}: {e}")
        else:
            self.sigNewPosition.emit(motor.name, axis, position)

    def _update_axis(self, motor: MotorProtocol, axis: str) -> bool:
        """Update the active axis of a motor.

        Parameters
        ----------
        motor : ``MotorProtocol``
            Motor instance to update.
        axis : ``str``
            New active axis.

        Returns
        -------
        ``bool``
            True if the axis was successfully updated.
            False otherwise.

        """
        s = motor.set(axis, prop="axis")
        try:
            s.wait(self._ctrl_info.timeout)
        except Exception as e:
            self.logger.exception(f"Failed set axis on {motor.name}: {e}")
            s.set_exception(e)
        finally:
            return s.success
