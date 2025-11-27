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


def wait_for_events(events: Iterable[asyncio.Event]) -> MsgGenerator[asyncio.Event]:
    """Wait for any of the given input events to be set.

    This is an helper plan stub similar to `wait_for` in `bluesky.plan_stubs`,
    but in contrast it will return when any of the input events is set.

    Plan execution will be blocked until one of the events is set; but
    background tasks will proceed as usual.

    Parameters
    ----------
    events: Iterable[asyncio.Event]
        An iterable of asyncio events to wait for.

    Returns
    -------
    asyncio.Event
        The event that was set to unblock the plan.
    """
    ret: asyncio.Event = yield Msg("wait_for_any", None, events)
    return ret


async def _wait_for_events_in_engine(self: RunEngine, msg: Msg) -> asyncio.Event:
    """Instruct the run engine to wait for any of the given events to be set.

    Parameters
    ----------
    msg: Msg
        The message containing the events to wait for.
        Packs an iterable of asyncio.Event in `msg.args`.

    Returns
    -------
    asyncio.Event
        The event that was set to unblock the plan.
    """

    async def _inner_wait(event: asyncio.Event) -> asyncio.Event:
        await event.wait()
        return event

    events: Iterable[asyncio.Event] = msg.args[0]
    tasks = [asyncio.create_task(_inner_wait(event)) for event in events]
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

    # cancel all pending tasks
    for task in pending:
        task.cancel()

    return done.pop().result()


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
