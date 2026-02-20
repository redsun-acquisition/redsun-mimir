from __future__ import annotations

from queue import Queue
from threading import Thread
from typing import TYPE_CHECKING

from dependency_injector import providers
from sunflare.log import Loggable
from sunflare.presenter import Presenter
from sunflare.virtual import HasShutdown, IsInjectable, IsProvider, Signal

from ..protocols import MotorProtocol

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    from bluesky.protocols import Descriptor, Reading
    from sunflare.device import Device
    from sunflare.virtual import VirtualContainer


class MotorPresenter(Presenter, Loggable, IsProvider, IsInjectable, HasShutdown):
    """Presenter for motor stage control.

    Allows manual stage positioning by forwarding movement requests from
    [`MotorView`][redsun_mimir.view.MotorView] to the underlying motor
    devices via a background thread. Emits position updates back to the
    view once each move completes.

    Parameters
    ----------
    name :
        Identity key of the presenter.
    devices :
        Mapping of device names to device instances.
    **kwargs :
        Additional keyword arguments.

        - `timeout` (`float | None`): Status wait timeout in seconds.

    Attributes
    ----------
    sigNewPosition :
        Emitted from the background move thread when a move completes.
        Carries motor name (`str`), axis (`str`), and new position (`float`).

        !!! warning
            This signal is emitted from a background thread. Connect with
            `thread="main"` to ensure the slot runs on the Qt main thread:

            ```python
            container.signals["MotorPresenter"]["sigNewPosition"].connect(
                self.on_new_position, thread="main"
            )
            ```

    sigNewConfiguration :
        Emitted after a configuration change attempt.
        Carries motor name (`str`) and a mapping of parameter names
        to success status (`dict[str, bool]`).
    """

    sigNewPosition = Signal(str, str, float)
    sigNewConfiguration = Signal(str, dict[str, bool])

    def __init__(
        self,
        name: str,
        devices: Mapping[str, Device],
        /,
        **kwargs: Any,
    ) -> None:
        super().__init__(name, devices)
        self._timeout: float | None = kwargs.get("timeout", None)
        self._queue: Queue[tuple[str, str, float] | None] = Queue()

        self._motors = {
            name: model
            for name, model in devices.items()
            if isinstance(model, MotorProtocol)
        }

        self._daemon = Thread(target=self._run_loop, daemon=True)
        self._daemon.start()

        self.logger.info("Initialized")

    def models_configuration(self) -> dict[str, Reading[Any]]:
        r"""Get the current configuration readings of all motor devices.

        Returns a flat dict keyed by the canonical ``prefix:name\\property``
        scheme, merging all motors together (matching the detector pattern).

        Returns
        -------
        dict[str, Reading[Any]]
            Flat mapping of canonical keys to their current readings.
        """
        result: dict[str, Reading[Any]] = {}
        for motor in self._motors.values():
            result.update(motor.read_configuration())
        return result

    def models_description(self) -> dict[str, Descriptor]:
        r"""Get the configuration descriptors of all motor devices.

        Returns a flat dict keyed by the canonical ``prefix:name\\property``
        scheme, merging all motors together (matching the detector pattern).

        Returns
        -------
        dict[str, Descriptor]
            Flat mapping of canonical keys to their descriptors.
        """
        result: dict[str, Descriptor] = {}
        for motor in self._motors.values():
            result.update(motor.describe_configuration())
        return result

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
        bare = self._bare_name(motor)
        for key, value in config.items():
            self.logger.debug(f"Configuring {key} of {motor} to {value}")
            s = self._motors[bare].set(value, propr=key)
            try:
                s.wait(self._timeout)
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

    def _bare_name(self, device_label: str) -> str:
        """Resolve a device label to the bare device name used as dict key.

        Since keys are now keyed by bare device name only, this method
        returns the label unchanged. Kept for compatibility with any
        callers that may still pass a name.

        Parameters
        ----------
        device_label :
            Device name.
        """
        return device_label

    def shutdown(self) -> None:
        """Shutdown the presenter.

        Close the daemon thread and wait
        for it to finish its last task
        """
        self._queue.put(None)
        self._queue.join()

    def register_providers(self, container: VirtualContainer) -> None:
        """Register motor model info as a provider in the DI container."""
        container.motor_configuration = providers.Object(self.models_configuration())
        container.motor_description = providers.Object(self.models_description())
        container.register_signals(self)

    def inject_dependencies(self, container: VirtualContainer) -> None:
        """Connect to the virtual container signals."""
        container.signals["MotorView"]["sigMotorMove"].connect(self.move)
        container.signals["MotorView"]["sigConfigChanged"].connect(
            self.configure
        )

    def _run_loop(self) -> None:
        while True:
            # block until a task is available
            task = self._queue.get()
            if task is not None:
                motor, axis, position = task
                self.logger.debug(f"Moving {motor} to {position} on {axis}")
                self._do_move(self._motors[self._bare_name(motor)], axis, position)
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
        if axis not in motor.axis:
            self.logger.error(
                f"Axis {axis!r} is not available for motor {motor.name!r}"
            )
            return
        ret = self.configure(motor.name, {"axis": axis})
        if not ret:
            return
        s = motor.set(position)
        try:
            s.wait(self._timeout)
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
            s.wait(self._timeout)
        except Exception as e:
            self.logger.exception(f"Failed set axis on {motor.name}: {e}")
            s.set_exception(e)
        finally:
            return s.success
