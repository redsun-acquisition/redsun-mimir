from __future__ import annotations

from queue import SimpleQueue
from threading import Thread
from typing import TYPE_CHECKING

from dependency_injector import providers
from redsun.log import Loggable
from redsun.presenter import Presenter
from redsun.utils import find_signals
from redsun.virtual import HasShutdown, Signal

from redsun_mimir.protocols import MotorProtocol  # noqa: TC001

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    from bluesky.protocols import Descriptor, Reading
    from redsun.device import Device
    from redsun.virtual import VirtualContainer

    from redsun_mimir.device.axis import MotorAxis


class MotorPresenter(Presenter, Loggable):
    """Presenter for motor stage control.

    Allows manual stage positioning by forwarding movement requests from
    [`MotorView`][redsun_mimir.view.MotorView] to the individual axis
    objects via a background thread. Emits position updates back to the
    view once each move completes.

    Axes are discovered at initialisation by iterating over each device's
    [`children()`][redsun.device.Device.children] and retaining those that
    satisfy [`MotorProtocol`][redsun_mimir.protocols.MotorProtocol].

    Parameters
    ----------
    name :
        Identity key of the presenter.
    devices :
        Mapping of device names to device instances.
    timeout :
        Timeout for motor operations in seconds. Defaults to 2 seconds.

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
        timeout: float | None = None,
    ) -> None:
        super().__init__(name, devices)
        self._timeout: float | None = timeout or 2.0
        self._queue: SimpleQueue[tuple[str, str, float] | None] = SimpleQueue()

        # motor_name -> {axis_name -> MotorAxis}
        self._axes: dict[str, dict[str, MotorAxis]] = {}
        # motor_name -> container Device (for read/describe_configuration)
        self._motor_devices: dict[str, Device] = {}

        for dev_name, device in devices.items():
            found = {
                attr: child
                for attr, child in device.children()
                if isinstance(child, MotorProtocol)
            }
            if found:
                self._axes[dev_name] = found  # type: ignore[assignment]
                self._motor_devices[dev_name] = device

        if not self._axes:
            self.logger.warning("No motor devices found.")
        else:
            self.logger.debug(f"Found motor devices: {list(self._axes)}")

        self._daemon = Thread(target=self._run_loop, daemon=True)
        self._daemon.start()

        self.logger.info("Initialized")

    def models_configuration(self) -> dict[str, Reading[Any]]:
        """Get the current configuration readings of all motor devices."""
        result: dict[str, Reading[Any]] = {}
        for device in self._motor_devices.values():
            result.update(device.read_configuration())  # type: ignore[arg-type]
        return result

    def models_description(self) -> dict[str, Descriptor]:
        """Get the configuration descriptors of all motor devices."""
        result: dict[str, Descriptor] = {}
        for device in self._motor_devices.values():
            result.update(device.describe_configuration())  # type: ignore[arg-type]
        return result

    def move(self, motor: str, axis: str, position: float) -> None:
        """Enqueue a move of *axis* on *motor* to *position*."""
        self._queue.put((motor, axis, position))

    def configure(self, motor: str, config: dict[str, Any]) -> dict[str, bool]:
        """Update one or more axis step sizes and emit ``sigNewConfiguration``.

        Keys in *config* follow the ``"{motor}-{axis}-step_size"`` pattern.

        Parameters
        ----------
        motor :
            Motor device name.
        config :
            Mapping of configuration keys to new values.

        Returns
        -------
        dict[str, bool]
            Per-key success flags.
        """
        success_map: dict[str, bool] = {}
        axes = self._axes.get(motor, {})
        for key, value in config.items():
            # key format: "{motor}-{axis}-step_size"
            parts = key.split("-")
            if len(parts) >= 3 and parts[-1] == "step_size":
                axis_name = parts[-2]
                if axis_name in axes:
                    try:
                        axes[axis_name].step_size.set(float(value))
                        success_map[key] = True
                    except Exception as e:
                        self.logger.exception(f"Failed to set {key}: {e}")
                        success_map[key] = False
                else:
                    self.logger.error(f"Unknown axis {axis_name!r} for motor {motor!r}")
                    success_map[key] = False
            else:
                self.logger.error(f"Unsupported configuration key: {key!r}")
                success_map[key] = False
        self.sigNewConfiguration.emit(motor, success_map)
        return success_map

    def shutdown(self) -> None:
        """Send the sentinel and wait for the daemon thread to exit."""
        self._queue.put(None)
        self._daemon.join()
        for device in self._motor_devices.values():
            if isinstance(device, HasShutdown):
                device.shutdown()

    def register_providers(self, container: VirtualContainer) -> None:
        """Register motor model info as a provider in the DI container."""
        container.motor_configuration = providers.Object(self.models_configuration())
        container.motor_description = providers.Object(self.models_description())
        container.register_signals(self)

    def inject_dependencies(self, container: VirtualContainer) -> None:
        """Connect to the virtual container signals."""
        sigs = find_signals(container, ["sigMotorMove", "sigConfigChanged"])
        if "sigMotorMove" in sigs:
            sigs["sigMotorMove"].connect(self.move)
        if "sigConfigChanged" in sigs:
            sigs["sigConfigChanged"].connect(self.configure)

    def _run_loop(self) -> None:
        while True:
            task = self._queue.get()
            if task is None:
                break
            motor, axis, position = task
            self.logger.debug(f"Moving {motor} to {position} on {axis}")
            self._do_move(motor, axis, position)

    def _do_move(self, motor: str, axis: str, position: float) -> None:
        axes = self._axes.get(motor)
        if axes is None:
            self.logger.error(f"Unknown motor {motor!r}")
            return
        axis_obj = axes.get(axis)
        if axis_obj is None:
            self.logger.error(f"Axis {axis!r} is not available for motor {motor!r}")
            return
        s = axis_obj.set(position)
        try:
            s.wait(self._timeout)  # type: ignore[attr-defined]
        except Exception as e:
            self.logger.exception(f"Failed to move {motor}/{axis} to {position}: {e}")
        else:
            self.sigNewPosition.emit(motor, axis, position)
