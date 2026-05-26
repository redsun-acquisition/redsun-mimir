from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import PurePath
from typing import TYPE_CHECKING

import numpy as np
from ophyd_async.core import (
    StandardDetector,
    StreamResourceDataProvider,
    StreamResourceInfo,
    TriggerInfo,
    soft_signal_rw,
)
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
    from ophyd_async.core import PathProvider, SignalRW, StreamableDataProvider
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
    store_path_sig: SignalRW[str]

    async def prepare_unbounded(self, datakey_name: str) -> StreamableDataProvider:
        """Prepare the data provider for the median device.

        Always act as secondary: read the store path from the shared writer.
        """
        store_path = await self.store_path_sig.get_value()
        if not store_path:
            raise RuntimeError(
                "store_path_sig is empty — ensure the camera write phase "
                "ran before preparing the median."
            )
        self._store_path = store_path
        self.writer.set_store_path(PurePath(store_path))

        shape = self.writer.sources[datakey_name].shape
        capacity = self.writer.sources[datakey_name].capacity
        dtype_numpy = np.dtype(self.writer.sources[datakey_name].dtype_numpy).str
        self._drain_task = asyncio.create_task(self._drain(datakey_name))
        await self._drain_ready_event.wait()
        actual_capacity = capacity if capacity > 0 else None
        data_resource = StreamResourceInfo(
            data_key=datakey_name,
            shape=(actual_capacity, *shape),
            chunk_shape=shape,
            dtype_numpy=dtype_numpy,
            parameters={},
        )
        sig = self.writer.get_counter(datakey_name)
        return StreamResourceDataProvider(
            uri=self._store_path,
            resources=[data_resource],
            mimetype=self.writer.mimetype,
            collections_written_signal=sig,
        )

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
        store_path_sig: SignalRW[str],
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
            store_path_sig=store_path_sig,
            queue=queue,
        )

        self.add_detector_logics(trigger_logic, acquire_logic, data_logic)
        super().__init__(name)
