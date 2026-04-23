from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
from ophyd_async.core import (
    DetectorArmLogic,
    DetectorDataLogic,
    DetectorTriggerLogic,
    StreamResourceDataProvider,
    StreamResourceInfo,
    TriggerInfo,
)
from redsun.aio import run_coro
from redsun.log import Loggable
from redsun.storage import SourceInfo

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from typing import Any

    from ophyd_async.core import PathProvider, SignalRW
    from ophyd_async.core._data_providers import StreamableDataProvider
    from pymmcore_plus import CMMCorePlus as Core
    from redsun.storage import DataWriter

    from redsun_mimir.protocols import Array2D, ROIType


@dataclass
class MMTriggerLogic(DetectorTriggerLogic):
    """DetectorTriggerLogic for a pymmcore-plus camera device."""

    datakey_name: str
    core: Core
    writer: DataWriter
    roi: SignalRW[ROIType]
    dtype: SignalRW[str]

    async def prepare_internal(
        self, num: int, livetime: float, deadtime: float
    ) -> None:
        shape_array, np_dtype = await asyncio.gather(
            self.roi.get_value(), self.dtype.get_value()
        )
        shape: tuple[int, ...] = tuple(shape_array.tolist())
        if len(shape) != 4:
            raise ValueError(f"Expected shape array of length 4, got {len(shape)}")
        actual_shape = (shape[2] - shape[0], shape[3] - shape[1])
        self.writer.register(
            self.datakey_name,
            SourceInfo(dtype_numpy=np_dtype, shape=actual_shape, capacity=num),
        )

    async def default_trigger_info(self) -> TriggerInfo:
        return TriggerInfo(number_of_events=0)


@dataclass
class MMArmLogic(DetectorArmLogic, Loggable):
    """DetectorArmLogic for a pymmcore-plus camera device."""

    datakey_name: str
    """Data key name to use for writing data from this device."""

    core: Core
    """MM core."""

    writer: DataWriter
    """Data writer object."""

    set_buffer: Callable[[Array2D], None]
    """Callable to set the current image buffer on the device."""

    write_sig: SignalRW[bool]
    """Signal to control whether the arm logic should enable writing to disk."""

    _pump_task: asyncio.Task[Any] | None = field(default=None, init=False)
    _stop_event: asyncio.Event = field(init=False)

    def __post_init__(self) -> None:
        async def _make_event() -> asyncio.Event:
            return asyncio.Event()

        self._stop_event = run_coro(_make_event())

    async def arm(self) -> None:
        """Start the acquisition acquiring from the camera."""
        self.core.startContinuousSequenceAcquisition()
        self._stop_event.clear()
        self._pump_task = asyncio.create_task(self._pump())

    async def wait_for_idle(self) -> None:
        # TODO: maybe the await on
        # the pump task should be moved here
        ...

    async def disarm(self, on_unstage: bool) -> None:
        if not self._stop_event.is_set():
            self._stop_event.set()
        if self._pump_task is not None:
            await self._pump_task
            self._pump_task = None
        self.core.stopSequenceAcquisition()
        await self.write_sig.set(False)
        if self.writer.is_open:
            self.writer.unregister(self.datakey_name)
            if len(self.writer.sources) == 0:
                self.writer.close(reset_path=on_unstage)

    async def _pump(self) -> None:
        exposure_ms = self.core.getExposure()
        sleep_s = exposure_ms / 1000.0
        capacity = self.writer.sources[self.datakey_name].capacity
        frame_cnt = 0
        while not self._stop_event.is_set():
            while self.core.getRemainingImageCount() < 1:
                await asyncio.sleep(sleep_s)
            img = self.core.popNextImage()
            self.set_buffer(img)
            if await self.write_sig.get_value():
                if not self.writer.is_open:
                    self.writer.open()
                if capacity is not None:
                    # if capaciy is set,
                    # write only up to the current capacity
                    if frame_cnt < capacity:
                        self.writer.write(self.datakey_name, img)
                else:
                    # if capacity is not set, always write
                    # until disarm is called
                    self.writer.write(self.datakey_name, img)
                frame_cnt = await self.writer.image_counter.get_value()
                self.logger.debug(f"Frame count updated {frame_cnt}")


@dataclass
class MMDataLogic(DetectorDataLogic, Loggable):
    writer: DataWriter
    path_provider: PathProvider

    def get_hinted_fields(self, datakey_name: str) -> Sequence[str]:
        return [datakey_name]

    async def prepare_unbounded(self, datakey_name: str) -> StreamableDataProvider:
        path_info = self.path_provider(datakey_name)
        extension = self.writer.file_extension
        if not self.writer.is_path_set():
            write_path = path_info.directory_path / ".".join(
                [path_info.filename, extension]
            )
            self.writer.set_store_path(write_path)
            self.logger.debug(f"Writer path set to {write_path}")

        shape = self.writer.sources[datakey_name].shape
        capacity = self.writer.sources[datakey_name].capacity
        dtype_numpy = np.dtype(self.writer.sources[datakey_name].dtype_numpy).str

        data_resource = StreamResourceInfo(
            data_key=datakey_name,
            shape=(capacity, *shape),
            chunk_shape=shape,
            dtype_numpy=dtype_numpy,
            parameters={},
        )

        # TODO: this seems to be used primarely for
        # HDF5 files; maybe a custom provider could be
        # implemented for Zarr
        return StreamResourceDataProvider(
            uri=f"{path_info.directory_path}{path_info.filename}.{extension}",
            resources=[data_resource],
            mimetype=self.writer.mimetype,
            collections_written_signal=self.writer.image_counter,
        )
