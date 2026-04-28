from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from redsun_mimir.device._common import BaseArmLogic, BaseDataLogic, BaseTriggerLogic

if TYPE_CHECKING:
    from collections.abc import Callable

    from pymmcore_plus import CMMCorePlus as Core

    from redsun_mimir.protocols import Array2D


@dataclass
class MMTriggerLogic(BaseTriggerLogic): ...


@dataclass
class MMArmLogic(BaseArmLogic):
    core: Core
    set_buffer: Callable[[Array2D], None]

    async def _start_acquisition(self) -> None:
        self.core.startContinuousSequenceAcquisition()

    async def _stop_acquisition(self) -> None:
        if self.core.isSequenceRunning():
            self.core.stopSequenceAcquisition()

    async def _pump(self) -> None:
        exposure_ms = self.core.getExposure()
        sleep_s = exposure_ms / 1000.0
        capacity = self.writer.sources[self.datakey_name].capacity
        frame_cnt = 0
        write_forever = capacity == 0
        while not self._stop_event.is_set():
            while self.core.getRemainingImageCount() < 1:
                await asyncio.sleep(sleep_s)
            img = self.core.popNextImage()
            self.set_buffer(img)
            if await self.write_sig.get_value():
                if not self.writer.is_open:
                    self.writer.open()
                if write_forever or frame_cnt < capacity:
                    self.writer.write(self.datakey_name, img)
                    frame_cnt = await self.writer.get_counter(
                        self.datakey_name
                    ).get_value()
                    self.logger.debug(
                        f"Frame count updated for {self.datakey_name}: {frame_cnt}"
                    )


class MMDataLogic(BaseDataLogic): ...
