from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

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
    queue: asyncio.Queue[Array2D]

    async def _pump(self) -> None:
        sleep_s = self.core.getExposure() / 1000.0

        await self._arm_event.wait()

        self.core.startContinuousSequenceAcquisition()
        while not self._disarm_event.is_set():
            if self.core.getRemainingImageCount() < 1:
                await asyncio.sleep(sleep_s)
            else:
                img = self.core.popNextImage()
                self.set_buffer(img)
                self.queue.put_nowait(img)
        self.core.stopSequenceAcquisition()


@dataclass
class MMDataLogic(BaseDataLogic, Loggable):
    write_sig: SignalRW[bool]
    queue: asyncio.Queue[Array2D]
    store_path_sig: SignalRW[str]

    async def should_allocate_path(self) -> bool:
        return await self.write_sig.get_value()  # type: ignore

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
                img = await self.queue.get()
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
