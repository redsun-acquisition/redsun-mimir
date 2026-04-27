from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from ophyd_async.core import StandardDetector, TriggerInfo

from redsun_mimir.device._common import BaseArmLogic, BaseDataLogic, BaseTriggerLogic
from redsun_mimir.device.signals import writeable_buffer_signal

if TYPE_CHECKING:
    from ophyd_async.core import SignalRW
    from redsun.storage import DataWriter

    from redsun_mimir.protocols import Array2D, ROIType
    from redsun_mimir.storage import SessionPathProvider


@dataclass
class MedianTriggerLogic(BaseTriggerLogic):
    """Trigger logic for the median device."""

    async def default_trigger_info(self) -> TriggerInfo:
        """Return default trigger info for the median device."""
        return TriggerInfo(number_of_events=1)


@dataclass
class MedianArmLogic(BaseArmLogic):
    """Arm logic for the median device."""

    buffer: SignalRW[Array2D]

    async def _start_acquisition(self) -> None:
        pass  # no hardware

    async def _stop_acquisition(self) -> None:
        pass  # no hardware

    async def _pump(self) -> None:
        while not self._stop_event.is_set():
            await asyncio.sleep(0)
            if await self.write_sig.get_value():
                val = await self.buffer.get_value()
                if val is not None and np.asarray(val).size > 0:
                    if not self.writer.is_open:
                        self.writer.open()
                    self.writer.write(self.datakey_name, np.asarray(val))
                    self.logger.debug("Median frame written to disk")
                self._stop_event.set()


class MedianDataLogic(BaseDataLogic):
    """Data logic for the median device.

    Just a placeholder, behavior
    is the same as the default data logic.
    """


class MedianDevice(StandardDetector):
    """A soft device that computes the median of a stack of images.

    Also allows the stack to be written to disk for post-processing.
    It is meant to be used as a child device in a concrete device.
    """

    def __init__(
        self,
        parent_name: str,
        roi_sig: SignalRW[ROIType],
        dtype_sig: SignalRW[str],
        write_sig: SignalRW[bool],
        writer: DataWriter,
        path_provider: SessionPathProvider,
    ) -> None:
        self.buffer = writeable_buffer_signal(roi_sig, dtype_sig)
        self.write_sig = write_sig
        self.writer = writer
        name = f"{parent_name}_median"

        trigger_logic = MedianTriggerLogic(
            datakey_name=name,
            roi=roi_sig,
            dtype=dtype_sig,
        )
        arm_logic = MedianArmLogic(
            datakey_name=name,
            writer=self.writer,
            buffer=self.buffer,
            write_sig=self.write_sig,
        )
        data_logic = MedianDataLogic(
            writer=self.writer,
            path_provider=path_provider,
        )

        self.add_detector_logics(trigger_logic, arm_logic, data_logic)
        super().__init__(name)
