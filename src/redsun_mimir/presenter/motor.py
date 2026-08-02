from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from redsun.aio import run_coro
from redsun.device.protocols import HasAsyncShutdown
from redsun.log import Loggable
from redsun.presenter import Presenter
from redsun.virtual import slot

from redsun_mimir.protocols import MotorProtocol
from redsun_mimir.providers import MOTOR_DESCRIPTION, MOTOR_READBACKS, MOTOR_READINGS

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    from bluesky.protocols import Descriptor, Reading
    from ophyd_async.core import Device, SignalR
    from redsun.virtual import VirtualContainer


class MotorPresenter(Presenter, Loggable):
    """Presenter for motor stage control.

    Allows manual stage positioning by forwarding movement requests to the
    individual axis objects. `move` is a coroutine connected directly to the
    requesting signal, so the emitting thread never waits for the device.

    Moves are serialised per device: a stage that writes several coordinates on
    every set cannot have two of them in flight at once.

    Positions are not announced: the axis readbacks are published as
    [`MOTOR_READBACKS`][redsun_mimir.providers.MOTOR_READBACKS] and whoever
    displays them subscribes to those instead.

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
    """

    def __init__(
        self,
        name: str,
        devices: Mapping[str, Device],
        /,
        timeout: float | None = None,
    ) -> None:
        super().__init__(name, devices)
        self._timeout = timeout or 2.0

        self._motors: dict[str, MotorProtocol] = {
            name: device
            for name, device in devices.items()
            if isinstance(device, MotorProtocol)
        }
        self._locks = {name: asyncio.Lock() for name in self._motors}

        self.logger.info("Initialized")

    def devices_readings(self) -> dict[str, Reading[Any]]:
        """Get the current configuration readings of all motor devices."""
        result: dict[str, Reading[Any]] = {}
        for device in self._motors.values():
            result.update(run_coro(device.read()))
        return result

    def devices_description(self) -> dict[str, Descriptor]:
        """Get the configuration descriptors of all motor devices."""
        result: dict[str, Descriptor] = {}
        for device in self._motors.values():
            result.update(run_coro(device.describe()))
        return result

    def devices_readbacks(self) -> dict[str, SignalR[float]]:
        """Get the readback signal of every motor axis, by data key."""
        return {
            movable.name: movable.movable_logic.readback
            for device in self._motors.values()
            for movable in device.axis.values()
        }

    @slot
    async def move(self, motor: str, axis: str, delta: float) -> None:
        """Move *axis* by *delta*.

        Parameters
        ----------
        motor : str
            Device name.
        axis : str
            Axis name within that device.
        delta : float
            Displacement from the current position, in the axis' units.
        """
        # one lock per device, not per axis: a Micro-Manager XY stage writes
        # both coordinates on every set, so a concurrent move on the sibling
        # axis would carry a stale value for this one and revert it
        async with self._locks[motor]:
            movable = self._motors[motor].axis[axis]
            await movable.set((await movable.locate())["readback"] + delta)

    def shutdown(self) -> None:
        """Shutdown all motor devices."""
        for device in self._motors.values():
            if isinstance(device, HasAsyncShutdown):
                run_coro(device.shutdown())

    def register_providers(self, container: VirtualContainer) -> None:
        """Register motor model info as a provider in the DI container."""
        container.provide(MOTOR_READINGS, self.devices_readings())
        container.provide(MOTOR_DESCRIPTION, self.devices_description())
        container.provide(MOTOR_READBACKS, self.devices_readbacks())
        container.register_signals(self)
