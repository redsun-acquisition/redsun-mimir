from __future__ import annotations

from typing import TYPE_CHECKING

from dependency_injector import providers
from redsun.device.protocols import HasAsyncShutdown
from redsun.log import Loggable
from redsun.presenter import Presenter
from redsun.utils import find_signals
from redsun.utils.aio import run_coro
from redsun.virtual import Signal

from redsun_mimir.protocols import MotorProtocol  # noqa: TC001

if TYPE_CHECKING:
    from collections.abc import Mapping
    from concurrent.futures import Future
    from typing import Any

    from bluesky.protocols import Descriptor, Reading
    from ophyd_async.core import Device
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
    """

    sigNewPosition = Signal(str, str, float)

    def __init__(
        self,
        name: str,
        devices: Mapping[str, Device],
        /,
        timeout: float | None = None,
    ) -> None:
        super().__init__(name, devices)
        self._timeout: float = timeout or 2.0

        self._motors: dict[str, MotorProtocol] = {
            name: device
            for name, device in devices.items()
            if isinstance(device, MotorProtocol)
        }
        self.futures: set[Future[None]] = set()

        self.logger.info("Initialized")

    def models_configuration(self) -> dict[str, Reading[Any]]:
        """Get the current configuration readings of all motor devices."""
        result: dict[str, Reading[Any]] = {}
        for device in self._motors.values():
            result.update(run_coro(device.read_configuration()))
        return result

    def models_description(self) -> dict[str, Descriptor]:
        """Get the configuration descriptors of all motor devices."""
        result: dict[str, Descriptor] = {}
        for device in self._motors.values():
            result.update(run_coro(device.describe_configuration()))
        return result

    def move(self, motor: str, axis: str, position: float) -> None:
        """Dispatch an async move of *axis* on *motor* to *position*."""
        run_coro(self._move(motor, axis, position))

    async def _move(self, motor: str, axis: str, position: float) -> None:
        """Move an axis and emit the new position on completion."""
        await self._motors[motor].axis[axis].set(position)
        self.sigNewPosition.emit(motor, axis, position)

    def shutdown(self) -> None:
        """Shutdown all motor devices."""
        for device in self._motors.values():
            if isinstance(device, HasAsyncShutdown):
                run_coro(device.shutdown())

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
