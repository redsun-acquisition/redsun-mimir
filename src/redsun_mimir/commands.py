from __future__ import annotations

import asyncio
from functools import partial
from typing import TYPE_CHECKING

from redsun_mimir.protocols import HasCache

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from typing import Any, Literal

    from bluesky.protocols import Reading, Status
    from bluesky.utils import Msg
    from redsun.engine import RunEngine

    from redsun_mimir.actions import SRLatch

__all__ = ["wait_for_actions", "register_bound_command"]


async def wait_for_actions(self: RunEngine, msg: Msg) -> tuple[str, SRLatch] | None:
    """Instruct the run engine to wait for any of the given latches to be set or reset.

    Parameters
    ----------
    msg: Msg
        The message containing the latches to wait for.
        Packs a map of SRLatch in `msg.args` and a timeout in `msg.kwargs`.

        Expected message format:

        Msg("wait_for_actions", None, latches, timeout=timeout, wait_for="set")

    Returns
    -------
    tuple[str, SRLatch] | None
        A tuple containing the name and the latch that was set/reset to unblock the plan;
        None if timeout occurred before any latch changed state.
    """
    latch_map: Mapping[str, SRLatch] = msg.args[0]
    timeout: float | None = msg.kwargs.get("timeout", None)
    wait_for: Literal["set", "reset"] = msg.kwargs.get("wait_for", "set")

    # Create a mapping to track which task corresponds to which latch
    if wait_for == "set":
        latch_tasks = {
            asyncio.create_task(latch.wait_for_set(), name=name)
            for name, latch in latch_map.items()
        }
    else:
        latch_tasks = {
            asyncio.create_task(latch.wait_for_reset(), name=name)
            for name, latch in latch_map.items()
        }

    done, pending = await asyncio.wait(
        latch_tasks, return_when=asyncio.FIRST_COMPLETED, timeout=timeout
    )

    # Cancel all pending tasks
    for task in pending:
        task.cancel()

    # Return the latch that changed state
    if not done:
        return None
    completed_task = done.pop()
    task_name = completed_task.get_name()
    return task_name, latch_map[task_name]


async def stash(self: RunEngine, msg: Msg) -> Status:
    """Instruct the run engine to stash the given readings in the model cache.

    Parameters
    ----------
    self: RunEngine
        The run engine instance.
    msg: Msg
        The message containing the readings to stash.
        Expected message format:

        Msg("stash", obj, readings)

        - obj: the model object to stash the readings for (implements `HasCache` protocol).
        - readings: a dict of readings to stash in the model cache.
    """
    obj = msg.obj
    if not isinstance(obj, HasCache):
        raise TypeError(
            f"Object {obj} does not support caching. It must implement the HasCache protocol."
        )
    if len(msg.args) != 1:
        raise RuntimeError(
            "Expected only one positional argument in the message after the object."
        )
    readings: dict[str, Reading[Any]] = msg.args[0]
    group: str | None = dict(msg.kwargs).get("group", None)
    if not group:
        raise RuntimeError("Expected a 'group' keyword argument in the message.")
    status = obj.stash(readings)

    self._add_status_to_group(obj, status, group, action="stash")

    return status


async def clear_cache(self: RunEngine, msg: Msg) -> Status:
    """Instruct the run engine to clear the model cache.

    Parameters
    ----------
    self: RunEngine
        The run engine instance.
    msg: Msg
        The message containing the object whose cache to clear.
        Expected message format:

        Msg("clear_cache", obj, name)

        - obj: the model object to clear the cache for (implements `HasCache` protocol).
        - name: the device name associated with the cache to clear.
    """
    obj = msg.obj
    if not isinstance(obj, HasCache):
        raise TypeError(
            f"Object {obj} does not support caching. It must implement the HasCache protocol."
        )
    group: str | None = dict(msg.kwargs).get("group", None)
    if not group:
        raise RuntimeError("Expected a 'group' keyword argument in the message.")
    status = obj.clear()

    self._add_status_to_group(obj, status, group, action="clear")

    return status


def register_bound_command(
    engine: RunEngine,
    command: Callable[[RunEngine, Msg], Any],
) -> None:
    """Register a custom command in the given run engine.

    In contrast to `RunEngine.register_command`, this function
    binds the command to the given run engine instance.

    Parameters
    ----------
    engine: RunEngine
        The run engine to register the command in.
    command: Callable[[RunEngine, Msg], Any]
        The command function to register.
        The function must accept a `RunEngine` instance and a `Msg` object as input.
    """
    bound_command = partial(command, engine)
    command_name = command.__name__
    engine.register_command(command_name, bound_command)
