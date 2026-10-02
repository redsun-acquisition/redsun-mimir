from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from redsun import DevicesOf, slot
from redsun.aio import run_coro
from redsun.log import Loggable

from redsun_mimir.protocols import MotorProtocol  # noqa: TC001

if TYPE_CHECKING:
    from typing import Any

    from bluesky.protocols import Descriptor, Reading
    from ophyd_async.core import SignalR


class MotorPresenter(Loggable):
    """Presenter for manual motor stage positioning.

    `move` is a coroutine connected directly to the requesting signal, so the
    emitting thread never waits for the device. A move repeats until
    `stop_step` is called for its device. Moves are serialised per device: a
    stage writing several coordinates on every set cannot have two in flight
    at once. Positions are not announced; `devices_readbacks`
    returns the axis readback signals for whoever displays them. An axis is
    reached as `axis[name]` on its device.

    Parameters
    ----------
    timeout
        Timeout for motor operations in seconds; `None` means `2.0`.
    """

    def __init__(
        self,
        name: str,
        *,
        motors: DevicesOf[MotorProtocol],
        timeout: float | None = None,
    ) -> None:
        self.name = name
        self._timeout = timeout or 2.0
        self._motors = motors
        self._locks = {name: asyncio.Lock() for name in self._motors}
        self._presses = dict.fromkeys(self._motors, 0)

        self.logger.info("Initialized")

    def motor_readings(self) -> dict[str, Reading[Any]]:
        """Return the current readings of every motor, by data key."""
        result: dict[str, Reading[Any]] = {}
        for device in self._motors.values():
            result.update(run_coro(device.read()))
        return result

    def motor_descriptors(self) -> dict[str, Descriptor]:
        """Return the descriptors of every motor, by data key."""
        result: dict[str, Descriptor] = {}
        for device in self._motors.values():
            result.update(run_coro(device.describe()))
        return result

    def devices_readbacks(self) -> dict[str, SignalR[float]]:
        """Return the readback signal of every motor axis, by data key."""
        return {
            movable.name: movable.movable_logic.readback
            for device in self._motors.values()
            for movable in device.axis.values()
        }

    @slot
    async def move(self, motor: str, axis: str, delta: float) -> None:
        """Move *axis* of *motor* by *delta* repeatedly, in the axis' units.

        Each move starts once the previous one lands. The repetition ends
        after the move in flight when `stop_step` is called for *motor*, or
        when another move starts on it.
        """
        self._presses[motor] += 1
        press = self._presses[motor]
        # one lock per device, not per axis: a Micro-Manager XY stage writes
        # both coordinates on every set, so a concurrent move on the sibling
        # axis would carry a stale value for this one and revert it
        async with self._locks[motor]:
            movable = self._motors[motor].axis[axis]
            self.logger.info(f"Moving {movable.name} by {delta}")
            while True:
                await movable.set((await movable.locate())["readback"] + delta)
                if self._presses[motor] != press:
                    break

    @slot
    async def stop_step(self, motor: str) -> None:
        """End the move repeating on *motor* once its move in flight lands."""
        # a coroutine, like `move`, so it is queued behind the move it ends:
        # called on the emitting thread it could run before that move starts
        self._presses[motor] += 1
