from __future__ import annotations

import asyncio

from bluesky.run_engine import call_in_bluesky_event_loop


class EventManager:
    """Creates and manages asyncio.Event objects.

    These are created within the Bluesky event loop,
    and are used to communicate with plans running in the RunEngine.
    """

    def __init__(self) -> None:
        self.events: dict[str, asyncio.Event] = {}

    async def _create_event(self, name: str) -> asyncio.Event:
        self.events[name] = asyncio.Event()
        return self.events[name]

    def create_event(self, name: str) -> asyncio.Event:
        """Create an asyncio.Event with the given name.

        Parameters
        ----------
        name: str
            The name of the event to create.

        Returns
        -------
        asyncio.Event
            The created event.
        """
        return call_in_bluesky_event_loop(self._create_event(name))
