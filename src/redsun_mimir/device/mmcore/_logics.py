from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import culsans
from redsun.log import Loggable

from redsun_mimir.device._logics import (
    BaseAcquireLogic,
    BaseDataLogic,
    BaseTriggerLogic,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ophyd_async.core import SignalRW, StreamableDataProvider
    from pymmcore_plus import CMMCorePlus as Core

    from redsun_mimir.protocols import Array2D


@dataclass
class MMTriggerLogic(BaseTriggerLogic): ...


@dataclass
class MMAcquireLogic(BaseAcquireLogic):
    core: Core
    set_buffer: Callable[[Array2D], None]
    queue: culsans.Queue[Array2D]

    def _acquisition_loop(self) -> None:
        """Synchronous frame-grab loop; runs in a worker thread via asyncio.to_thread."""
        sleep_s = self.core.getExposure() / 1000.0
        self.core.startContinuousSequenceAcquisition()
        while not self._disarm_event.is_set():
            if self.core.getRemainingImageCount() < 1:
                time.sleep(sleep_s)
            else:
                img = self.core.popNextImage()
                self.set_buffer(img)
                self.queue.sync_put(img)
        self.core.stopSequenceAcquisition()

    async def pump(self) -> None:
        await self._arm_event.wait()
        await asyncio.to_thread(self._acquisition_loop)


@dataclass
class MMDataLogic(BaseDataLogic, Loggable):
    write_sig: SignalRW[bool]
    queue: culsans.Queue[Array2D]
    store_path_sig: SignalRW[str]

    async def prepare_unbounded(self, datakey_name: str) -> StreamableDataProvider:
        provider = await super().prepare_unbounded(datakey_name)
        await self.store_path_sig.set(self._store_path)
        return provider

    async def _drain(self, datakey_name: str) -> None:
        capacity = self.writer.sources[datakey_name].capacity
        frame_cnt = 0
        write_forever = capacity == 0
        self._drain_ready_event.set()
        try:
            while True:
                img = await self.queue.async_get()
                if await self.write_sig.get_value():
                    if not self.writer.is_open:
                        self.writer.open()
                    if write_forever or frame_cnt < capacity:
                        self.writer.write(datakey_name, img)
                        frame_cnt += 1
                        self.logger.debug(f"Frame {frame_cnt} written to disk.")
                    else:
                        # capacity reached, regardless of the
                        # value of close event, exit
                        break
        except asyncio.CancelledError:
            ...
        finally:
            self.writer.unregister(datakey_name)
            self.close_writer_if_idle()
