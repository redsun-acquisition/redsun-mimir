from __future__ import annotations

from typing import TYPE_CHECKING

import bluesky.plan_stubs as bps
from bluesky.utils import Msg

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Mapping, Sequence
    from typing import Final

    from bluesky.protocols import Flyable
    from bluesky.utils import MsgGenerator

SIXTY_FPS: Final[float] = 1.0 / 60.0


def wait_for_any(
    events: Mapping[str, asyncio.Event], timeout: float = 0.001
) -> MsgGenerator[tuple[str, asyncio.Event] | None]:
    """Wait for any of the given input events to be set.

    This is an helper plan stub similar to `wait_for` in `bluesky.plan_stubs`,
    but in contrast it will return when any of the input events is set.

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
        "wait_for_any", events, timeout=timeout
    )
    return ret


def collect_while_waiting(
    objs: Sequence[Flyable],
    events: Mapping[str, asyncio.Event],
    stream_name: str,
    refresh_period: float = SIXTY_FPS,
) -> MsgGenerator[tuple[str, asyncio.Event]]:
    """Collect data from the given Flyable objects while waiting.

    Parameters
    ----------
    objects : ``Sequence[EventCollectable]``
        The objects to collect data from.
    wait_group : ``str``
        The group identifier to wait on.
    stream_name : ``str``
        The name of the stream to collect data into.
    refresh_period : ``float``, optional
        The period (in seconds) to refresh the collection. Default is 60 Hz (1/60 s).

    Yields
    ------
    Msg
        Messages to wait and collect data from the objects.
    """
    event: tuple[str, asyncio.Event] | None = None
    while event is None:
        event = yield from wait_for_any(events, timeout=refresh_period)
        yield from bps.collect(
            *objs, name=stream_name, stream=True, return_payload=False
        )
    return event
