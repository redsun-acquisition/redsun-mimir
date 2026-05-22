from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ophyd_async.core import StandardDetector, TriggerInfo, soft_signal_rw
from redsun.aio import run_coro
from redsun.log import Loggable
from redsun.storage import SourceInfo

from redsun_mimir.device._logics import (
    BaseAcquireLogic,
    BaseDataLogic,
    BaseTriggerLogic,
)
from redsun_mimir.device.signals import writeable_buffer_signal

if TYPE_CHECKING:
    from ophyd_async.core import PathProvider, SignalRW
    from redsun.storage import DataWriter

    from redsun_mimir.protocols import Array2D, ROIType


@dataclass
class MedianTriggerLogic(BaseTriggerLogic):
    """Trigger logic for the median device."""

    async def prepare_internal(
        self, num: int, livetime: float, deadtime: float
    ) -> None:
        """Prepare the writer to accept only one frame - the median."""
        shape, np_dtype = await self._get_shape_and_dtype()
        self.writer.register(
            self.datakey_name,
            SourceInfo(dtype_numpy=np_dtype, shape=shape, capacity=1),  # always 1
        )

    async def default_trigger_info(self) -> TriggerInfo:
        """Return default trigger info for the median device."""
        return TriggerInfo(number_of_events=1)


@dataclass
class MedianAcquireLogic(BaseAcquireLogic):
    """Arm logic for the median device."""

    buffer: SignalRW[Array2D]
    buffer_ready: SignalRW[bool]
    queue: asyncio.Queue[Array2D]

    async def _pump(self) -> None:
        try:
            await self._arm_event.wait()
            while not await self.buffer_ready.get_value():
                await asyncio.sleep(0)
            self.queue.put_nowait(await self.buffer.get_value())
            await self.buffer_ready.set(False)
            await self._disarm_event.wait()
        except asyncio.CancelledError:
            ...
        finally:
            ...


@dataclass
class MedianDataLogic(BaseDataLogic, Loggable):
    """Data logic for the median device.

    Write a single frame to disk.
    """

    write_sig: SignalRW[bool]
    queue: asyncio.Queue[Array2D]

    async def _drain(self, datakey_name: str) -> None:
        self._drain_ready_event.set()
        try:
            img = await self.queue.get()
            if await self.write_sig.get_value():
                if not self.writer.is_open:
                    self.writer.open()
                self.writer.write(datakey_name, img)
                self.logger.debug("Median written to disk.")
        except asyncio.CancelledError:
            ...
        finally:
            self.writer.unregister(datakey_name)
            self.close_writer_if_idle()


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
        writer: DataWriter,
        path_provider: PathProvider,
    ) -> None:
        async def _make_queue() -> asyncio.Queue[Array2D]:
            return asyncio.Queue(maxsize=1)

        self.buffer = writeable_buffer_signal(roi_sig, dtype_sig)
        self.writer = writer
        self.write_sig = soft_signal_rw(bool, initial_value=False)
        self.buffer_ready = soft_signal_rw(bool, initial_value=False)
        name = f"{parent_name}-median"

        queue = run_coro(_make_queue())

        trigger_logic = MedianTriggerLogic(
            datakey_name=name,
            writer=writer,
            roi=roi_sig,
            dtype=dtype_sig,
        )
        acquire_logic = MedianAcquireLogic(
            buffer=self.buffer,
            queue=queue,
            buffer_ready=self.buffer_ready,
        )
        data_logic = MedianDataLogic(
            writer=self.writer,
            path_provider=path_provider,
            write_sig=self.write_sig,
            queue=queue,
        )

        self.add_detector_logics(trigger_logic, acquire_logic, data_logic)
        super().__init__(name)
