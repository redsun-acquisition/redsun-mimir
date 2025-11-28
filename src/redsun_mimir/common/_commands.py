from __future__ import annotations

import asyncio
from functools import partial
from typing import TYPE_CHECKING

from bluesky.utils import Msg

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from typing import Any

    from bluesky.utils import MsgGenerator
    from sunflare.engine import RunEngine


def wait_for_any(
    events: Iterable[asyncio.Event], timeout: float = 0.001
) -> MsgGenerator[asyncio.Event]:
    """Wait for any of the given input events to be set.

    This is an helper plan stub similar to `wait_for` in `bluesky.plan_stubs`,
    but in contrast it will return when any of the input events is set.

    Plan execution will be blocked until one of the events is set; but
    background tasks will proceed as usual.

    Parameters
    ----------
    events: Iterable[asyncio.Event]
        An iterable of asyncio events to wait for.

    timeout: float, optional
        The maximum time (in seconds) to wait for an event to be set.
        Default is 0.001 seconds.

    Returns
    -------
    asyncio.Event
        The event that was set to unblock the plan.
    """
    ret: asyncio.Event = yield Msg("wait_for", events, timeout=timeout)
    return ret


async def _wait_for_any(self: RunEngine, msg: Msg) -> asyncio.Event | None:
    """Instruct the run engine to wait for any of the given events to be set.

    Parameters
    ----------
    msg: Msg
        The message containing the events to wait for.
        Packs an iterable of asyncio.Event in `msg.args` and a timeout in `msg.kwargs`.

        Expected message format:

        Msg("wait_for_any", None, events, timeout=timeout)

        If timeout is not provided, a default value of 0.001 seconds is used.

    Returns
    -------
    asyncio.Event
        The event that was set to unblock the plan.
    """
    events: Iterable[asyncio.Event] = msg.args[0]
    timeout: float = msg.kwargs.get("timeout", 0.001)

    # Create a mapping to track which task corresponds to which event
    event_tasks = {asyncio.create_task(event.wait()): event for event in events}

    done, pending = await asyncio.wait(
        event_tasks.keys(), return_when=asyncio.FIRST_COMPLETED, timeout=timeout
    )

    # Cancel all pending tasks
    for task in pending:
        task.cancel()

    # Return the event that was set
    if not done:
        return None
    completed_task = done.pop()
    return event_tasks[completed_task]


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
