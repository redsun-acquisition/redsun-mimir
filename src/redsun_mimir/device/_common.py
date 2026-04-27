from __future__ import annotations

import abc
import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, Literal

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
    from collections.abc import Sequence

    from ophyd_async.core import PathProvider, SignalRW
    from ophyd_async.core._data_providers import StreamableDataProvider
    from redsun.storage import DataWriter

    from redsun_mimir.protocols import ROIType

AxisType = Literal["x", "y", "z"]

DEFAULT_TIMEOUT: Final[float] = 1.0


@dataclass
class BaseTriggerLogic(DetectorTriggerLogic):
    datakey_name: str
    writer: DataWriter
    roi: SignalRW[ROIType]
    dtype: SignalRW[str]

    async def prepare_internal(
        self, num: int, livetime: float, deadtime: float
    ) -> None:
        shape, np_dtype = await self._get_shape_and_dtype()
        self.writer.register(
            self.datakey_name,
            SourceInfo(dtype_numpy=np_dtype, shape=shape, capacity=num),
        )

    async def _get_shape_and_dtype(self) -> tuple[tuple[int, ...], str]:
        shape_array, np_dtype = await asyncio.gather(
            self.roi.get_value(), self.dtype.get_value()
        )
        shape = tuple(shape_array.tolist())
        if len(shape) != 4:
            raise ValueError(f"Expected shape array of length 4, got {len(shape)}")
        return (shape[2] - shape[0], shape[3] - shape[1]), np_dtype

    async def default_trigger_info(self) -> TriggerInfo:
        return TriggerInfo(number_of_events=0)


@dataclass
class BaseArmLogic(DetectorArmLogic, Loggable):
    datakey_name: str
    writer: DataWriter
    write_sig: SignalRW[bool]

    _pump_task: asyncio.Task[None] | None = field(default=None, init=False)
    _stop_event: asyncio.Event = field(init=False)

    def __post_init__(self) -> None:
        async def _make_event() -> asyncio.Event:
            return asyncio.Event()

        self._stop_event = run_coro(_make_event())

    async def arm(self) -> None:
        await self._start_acquisition()
        self._stop_event.clear()
        self._pump_task = asyncio.create_task(self._pump())

    async def wait_for_idle(self) -> None: ...

    async def disarm(self, on_unstage: bool) -> None:
        if not self._stop_event.is_set():
            self._stop_event.set()
        if self._pump_task is not None:
            await self._pump_task
            self._pump_task = None
        await self._stop_acquisition()
        await self.write_sig.set(False)
        if self.writer.is_open:
            self.writer.unregister(self.datakey_name)
            if len(self.writer.sources) == 0:
                self.writer.close(reset_path=on_unstage)

    @abc.abstractmethod
    async def _start_acquisition(self) -> None: ...

    @abc.abstractmethod
    async def _stop_acquisition(self) -> None: ...

    @abc.abstractmethod
    async def _pump(self) -> None: ...


@dataclass
class BaseDataLogic(DetectorDataLogic, Loggable):
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

        # when unlimited capacity is requested, the time axis of
        # shape requires a None flag to indicate it grows indefinetely
        actual_capacity = capacity if capacity > 0 else None

        data_resource = StreamResourceInfo(
            data_key=datakey_name,
            shape=(actual_capacity, *shape),
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
            collections_written_signal=self.writer.get_counter(datakey_name),
        )
