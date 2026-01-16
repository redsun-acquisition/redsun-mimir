from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import bluesky.plan_stubs as bps
from bluesky.utils import Msg

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Mapping, Sequence
    from typing import Any, Final

    from bluesky.protocols import Movable, Readable, Status
    from bluesky.utils import MsgGenerator

SIXTY_FPS: Final[float] = 1.0 / 60.0


def set_proprerty(
    obj: Movable[Any],
    value: Any,
    /,
    propr: str,
    timeout: float | None = None,
) -> MsgGenerator[Status]:
    """Set a property of a `Movable` object and wait for completion.

    Parameters
    ----------
    obj: Movable[Any]
        The Movable object to set.
    value: Any
        The value to set the property to.
    propr: str, keyword-only
        The property name to set.
    timeout: float, keyword-only, optional
        The maximum time (in seconds) to wait for the operation to complete.
        Default is None (wait indefinitely).

    Yields
    ------
    Msg
        Yields two messages:
        - `Msg("set", obj, value, propr=propr)`: to set the property.
        - `Msg("wait", None, timeout=timeout)`: to wait for the operation to complete.

    Returns
    -------
    Status
        The status object returned by the `set` method.
    """
    group = str(uuid.uuid4())
    status: Status = yield Msg("set", obj, value, group=group, propr=propr)
    yield Msg("wait", None, group=group, timeout=timeout)
    return status


def wait_for_actions(
    events: Mapping[str, asyncio.Event], timeout: float = 0.001
) -> MsgGenerator[tuple[str, asyncio.Event] | None]:
    """Wait for any of the given input events to be set.

    Plan execution will be blocked until one of the events is set; but
    background tasks will proceed as usual.

    Parameters
    ----------
    events: Mapping[str, asyncio.Event]
        A mapping of event names to asyncio.Event objects to wait for.

    timeout: float, optional
        The maximum time (in seconds) to wait for an event to be set.
        Default is 0.001 seconds.

    Returns
    -------
    asyncio.Event | None
        The event that was set to unblock the plan;
        None if timeout occurred before any event was set.
    """
    ret: tuple[str, asyncio.Event] | None = yield Msg(
        "wait_for_actions", None, events, timeout=timeout
    )
    return ret


def read_while_waiting(
    objs: Sequence[Readable[Any]],
    events: Mapping[str, asyncio.Event],
    stream_name: str = "primary",
    refresh_period: float = SIXTY_FPS,
) -> MsgGenerator[tuple[str, asyncio.Event]]:
    """Read a list of `Readable` objects while waiting for actions.

    Parameters
    ----------
    objs : ``Sequence[Readable[Any]]``
        The objects to trigger and read.
    events : ``Mapping[str, asyncio.Event]``
        A mapping of event names to asyncio.Event objects to wait for.
        Each event represents an action that can unblock the plan.
    stream_name : ``str``, optional
        The name of the stream to collect data into.
        Default is "primary".
    refresh_period : ``float``, optional
        The period (in seconds) to refresh the triggering and reading.
        Default is 60 Hz (1/60 s).

    Yields
    ------
    Msg
        Messages to wait and trigger/read the objects.

    Returns
    -------
    tuple[str, asyncio.Event]
        The event that was set to unblock the plan.
    """
    event: tuple[str, asyncio.Event] | None = None
    while event is None:
        yield from bps.checkpoint()
        event = yield from wait_for_actions(events, timeout=refresh_period)
        yield from bps.trigger_and_read(objs, name=stream_name)
    return event
