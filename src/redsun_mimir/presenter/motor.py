from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

from dependency_injector import providers
from redsun.engine import get_shared_loop
from redsun.log import Loggable
from redsun.presenter import Presenter
from redsun.utils import find_signals
from redsun.virtual import HasShutdown, Signal

from redsun_mimir.protocols import MotorProtocol  # noqa: TC001

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    from bluesky.protocols import Descriptor, Reading
    from ophyd_async.core import AsyncConfigurable, Device
    from redsun.virtual import VirtualContainer


class MotorPresenter(Presenter, Loggable):
    """Presenter for motor stage control.

    Allows manual stage positioning by forwarding movement requests from
    [`MotorView`][redsun_mimir.view.MotorView] to the individual axis
    objects.  Each move is dispatched to the shared bluesky event loop via
    [`asyncio.run_coroutine_threadsafe`][asyncio.run_coroutine_threadsafe]
    so the Qt main thread is never blocked.

    Axes are discovered at initialisation by iterating over each device's
    [`children()`][ophyd_async.core.Device.children] and retaining those that
    satisfy [`MotorProtocol`][redsun_mimir.protocols.MotorProtocol].

    Parameters
    ----------
    name :
        Identity key of the presenter.
    devices :
        Mapping of device names to device instances.
    timeout :
        Timeout for motor operations in seconds. Defaults to ``2.0``.

    Attributes
    ----------
    sigNewPosition :
        Emitted when a move completes successfully.
        Carries motor name (``str``), axis name (``str``), and new position
        (``float``).
    sigNewConfiguration :
        Emitted after a configuration change attempt.
        Carries motor name (``str``) and a mapping of parameter names to
        success status (``dict[str, bool]``).
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
        self._timeout: float = timeout or 2.0

        # motor_name -> {axis_name -> MotorProtocol}
        self._axes: dict[str, dict[str, MotorProtocol]] = {}
        # motor_name -> container Device (for read/describe_configuration)
        self._motor_devices: dict[str, Device] = {}

        for dev_name, device in devices.items():
            found: dict[str, MotorProtocol] = {
                attr: child
                for attr, child in device.children()
                if isinstance(child, MotorProtocol)
            }
            if found:
                self._axes[dev_name] = found
                self._motor_devices[dev_name] = device

        if not self._axes:
            self.logger.warning("No motor devices found.")
        else:
            self.logger.debug(f"Found motor devices: {list(self._axes)}")

        self.logger.info("Initialized")

    def models_configuration(self) -> dict[str, Reading[Any]]:
        """Get the current configuration readings of all motor devices."""
        loop = get_shared_loop()
        result: dict[str, Reading[Any]] = {}
        for device in self._motor_devices.values():
            result.update(
                asyncio.run_coroutine_threadsafe(
                    cast("AsyncConfigurable", device).read_configuration(), loop
                ).result()
            )
        return result

    def models_description(self) -> dict[str, Descriptor]:
        """Get the configuration descriptors of all motor devices."""
        loop = get_shared_loop()
        result: dict[str, Descriptor] = {}
        for device in self._motor_devices.values():
            result.update(
                asyncio.run_coroutine_threadsafe(
                    cast("AsyncConfigurable", device).describe_configuration(), loop
                ).result()
            )
        return result

    def move(self, motor: str, axis: str, position: float) -> None:
        """Dispatch an async move of *axis* on *motor* to *position*.

        Returns immediately; the move runs on the shared event loop.
        """
        loop = get_shared_loop()
        asyncio.run_coroutine_threadsafe(self._do_move(motor, axis, position), loop)

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
        loop = get_shared_loop()
        success_map: dict[str, bool] = {}
        axes = self._axes.get(motor, {})
        for key, value in config.items():
            parts = key.split("-")
            if len(parts) >= 3 and parts[-1] == "step_size":
                axis_name = parts[-2]
                if axis_name in axes:
                    future = asyncio.run_coroutine_threadsafe(
                        self._set_step_size(axes[axis_name], float(value)), loop
                    )
                    try:
                        future.result(timeout=self._timeout)
                        success_map[key] = True
                    except Exception:
                        self.logger.exception(f"Failed to set {key}")
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
        """Shutdown all motor devices."""
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

    async def _set_step_size(self, axis: MotorProtocol, value: float) -> None:
        """Wrap ``axis.step_size.set()`` as a coroutine for ``run_coroutine_threadsafe``."""
        await axis.step_size.set(value)

    async def _do_move(self, motor: str, axis: str, position: float) -> None:
        axes = self._axes.get(motor)
        if axes is None:
            self.logger.error(f"Unknown motor {motor!r}")
            return
        axis_obj = axes.get(axis)
        if axis_obj is None:
            self.logger.error(f"Axis {axis!r} is not available for motor {motor!r}")
            return
        self.logger.debug(f"Moving {motor}/{axis} → {position}")
        try:
            await asyncio.wait_for(axis_obj.set(position), timeout=self._timeout)
        except asyncio.TimeoutError:
            self.logger.warning(f"Move timeout: {motor}/{axis} → {position}")
        except Exception:
            self.logger.exception(f"Move failed: {motor}/{axis} → {position}")
        else:
            self.sigNewPosition.emit(motor, axis, position)
