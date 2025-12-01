from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from bluesky.run_engine import get_bluesky_event_loop

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Sequence
    from typing import Any, Literal, TypeAlias

    CoroutineOp: TypeAlias = Literal["create", "set", "clear"]
    EventCoroutine: TypeAlias = Callable[[str], Coroutine[Any, Any, None]]


__all__ = ["EventManager", "create"]


class EventManager:
    """Creates and manages asyncio.Event objects.

    These are created within the Bluesky event loop,
    and are used to communicate with plans running in the RunEngine.
    """

    events_op: dict[CoroutineOp, EventCoroutine]
    _events: dict[str, asyncio.Event]

    def __init__(self) -> None:
        self._events = {}
        self._events_op = {
            "create": self._create_event,
            "set": self._set_event,
            "clear": self._clear_event,
        }
        self._bluesky_loop: asyncio.AbstractEventLoop = get_bluesky_event_loop()
        assert self._bluesky_loop is not None

    async def _create_event(self, name: str) -> None:
        """Create an asyncio.Event with the given name.

        The event is bound to the Bluesky event loop
        running in the background thread of the RunEngine.
        """
        self._events[name] = asyncio.Event()

    async def _set_event(self, name: str) -> None:
        """Set an existing asyncio.Event with the given name."""
        event = self._events.get(name)
        if event is not None:
            event.set()

    async def _clear_event(self, name: str) -> None:
        """Clear an existing asyncio.Event with the given name."""
        event = self._events.get(name)
        if event is not None:
            event.clear()

    def manage_event(self, name: str, op: Literal["create", "set", "clear"]) -> None:
        """Create, set, or clear an asyncio.Event by name.

        Coroutines are executed within the Bluesky event loop.

        Parameters
        ----------
        name: str
            The name of the event to manage.
        op: Literal["create", "set", "clear"]
            The operation to perform on the event.
        """
        future = asyncio.run_coroutine_threadsafe(
            self._events_op[op](name), self._bluesky_loop
        )
        future.result()  # Wait for completion

    @property
    def events(self) -> dict[str, asyncio.Event]:
        """Return the list of managed events."""
        return self._events


def create(
    names: Sequence[str], manager: EventManager | None
) -> dict[str, asyncio.Event]:
    """Create multiple asyncio.Event objects by their names.

    Parameters
    ----------
    names: Sequence[str]
        The names of the events to create.
    manager: EventManager | None
        An optional EventManager instance to use for managing the events.
        If None, a new EventManager will be created and discarded after use.

    Returns
    -------
    dict[str, asyncio.Event]
        A mapping of event names to their corresponding asyncio.Event objects.
    """
    manager = EventManager() if not manager else manager
    for name in names:
        manager.manage_event(name, "create")
    return manager.events
