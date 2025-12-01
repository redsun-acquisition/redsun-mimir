from __future__ import annotations

import asyncio
from functools import partial
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from typing import Any

    from bluesky.utils import Msg
    from sunflare.engine import RunEngine


async def _wait_for_any(self: RunEngine, msg: Msg) -> tuple[str, asyncio.Event] | None:
    """Instruct the run engine to wait for any of the given events to be set.

    Parameters
    ----------
    msg: Msg
        The message containing the events to wait for.
        Packs an iterable of asyncio.Event in `msg.args` and a timeout in `msg.kwargs`.

        - `events`: Mapping[str, asyncio.Event]
        - `timeout`: float

        Expected message format:

        Msg("wait_for_any", events, timeout=timeout)

        If timeout is not provided, a default value of 0.001 seconds is used.

    Returns
    -------
    tuple[str, asyncio.Event] | None
        A tuple containing the name and the event that was set to unblock the plan;
        None if timeout occurred before any event was set.
    """
    event_map: Mapping[str, asyncio.Event] = msg.args[0]
    timeout: float = msg.kwargs.get("timeout", 0.001)

    # Create a mapping to track which task corresponds to which event
    event_tasks = {
        asyncio.create_task(event.wait(), name=name)
        for name, event in event_map.items()
    }

    done, pending = await asyncio.wait(
        event_tasks, return_when=asyncio.FIRST_COMPLETED, timeout=timeout
    )

    # Cancel all pending tasks
    for task in pending:
        task.cancel()

    # Return the event that was set
    if not done:
        return None
    completed_task = done.pop()
    task_name = completed_task.get_name()
    return task_name, event_map[task_name]


def register_bound_command(
    engine: RunEngine,
    command_name: str,
    command: Callable[[RunEngine, Msg], Any],
) -> None:
    """Register a custom command in the given run engine.

    In contrast to `RunEngine.register_command`, this function
    binds the command to the given run engine instance.

    Parameters
    ----------
    engine: RunEngine
        The run engine to register the command in.
    command_name: str
        The name of the command to register.
        It must match the string used in the `Msg` object.
    command: Callable[[RunEngine, Msg], Any]
        The command function to register.
        The function must accept a `RunEngine` instance and a `Msg` object as input.
    """
    bound_command = partial(command, engine)
    engine.register_command(command_name, bound_command)
