from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import culsans

from redsun_mimir.device._logics import BaseAcquireLogic

if TYPE_CHECKING:
    from collections.abc import Callable

    from pymmcore_plus import CMMCorePlus as Core

    from redsun_mimir.protocols import Array2D


@dataclass
class MMAcquireLogic(BaseAcquireLogic):
    """Acquire logic for Micro-Manager cameras.

    A background thread grabs frames continuously. **Storage sees every
    frame**; the buffer signal that feeds live visualization is refreshed at
    most once per `live_period`. Live frames now travel as Event documents
    (``bps.monitor`` on the buffer signal), so updating the signal on every
    grab would push the whole acquisition rate through the document router
    and the Qt main thread for no visual benefit.

    While a write window is active (`sink` is set, per `BaseAcquireLogic`)
    frames are pushed into storage through the sink's sync producer face -
    safe to call from a foreign thread. Capacity is enforced by the storage
    drain: once it shuts the queue down, `culsans.QueueShutDown` drops the
    sink and acquisition falls back to pure live view.

    Frames handed to the buffer signal are always **copies**: the viewer
    must never alias memory the camera or a queue may reuse or reclaim.
    """

    core: Core
    set_buffer: Callable[[Array2D], None]
    live_period: float = 0.1

    _stop_event: threading.Event = field(init=False, default_factory=threading.Event)
    _task: asyncio.Task[None] | None = field(default=None, init=False)
    _last_live_update: float = field(init=False, default=0.0)

    def _acquisition_loop(self) -> None:
        """Perform frame-grab loop in a separate thread."""
        # sleep_s = self.core.getExposure() / 1000.0
        # self.core.startContinuousSequenceAcquisition()
        # while not self._stop_event.is_set():
        #     if self.core.getRemainingImageCount() < 1:
        #         time.sleep(sleep_s)
        #     else:
        #         img = self.core.popNextImage()
        #         self.set_buffer(img)
        #         ...

        # TODO: if anyone is reading this, i truly apologize:
        # this shit is... shit; but there seems to be some
        # problems when dealing with the mmcore sequence API
        # and other devices, in particular with the daheng adapter;
        # since this is a prototype and i'm out of time
        # i don't have much of a choice for now... the loop above
        # should be the correct one... maybe this is a problem specific
        # to some adapters, no clue
        while not self._stop_event.is_set():
            img = self.core.snap()
            # storage first and unthrottled: a written frame must never be
            # dropped because the viewer was not due an update
            if self.sink is not None:
                try:
                    self.sink.put_nowait(img)
                except culsans.QueueShutDown:
                    # capacity reached: write window over, back to pure live view
                    self.sink = None
                except culsans.QueueFull:
                    self.logger.warning("Dropped a frame: sink queue is full.")
            self._refresh_live_view(img)

    def _refresh_live_view(self, img: Array2D) -> None:
        """Update the buffer signal at most once per `live_period`.

        Takes a copy so the viewer never holds a reference into memory the
        camera (or the sink queue) may reuse. When this loop is moved back
        onto Micro-Manager's sequence API, read the head of the circular
        buffer with a non-destructive peek (``getLastImage``) rather than
        ``popNextImage``: popping for the sake of the live view would consume
        frames that belong to storage.
        """
        now = time.monotonic()
        if now - self._last_live_update < self.live_period:
            return
        self._last_live_update = now
        self.set_buffer(img.copy())

    async def ensure_ready(self) -> None:
        self._stop_event.clear()
        self._task = asyncio.create_task(asyncio.to_thread(self._acquisition_loop))

    async def ensure_stopped(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            await self._task
            self._task = None
        self._close_sinks()
