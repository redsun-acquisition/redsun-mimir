from __future__ import annotations

import abc
import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, Literal

import numpy as np
from ophyd_async.core import (
    DetectorAcquireLogic,
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
class BaseAcquireLogic(DetectorAcquireLogic, Loggable):
    _pump_task: asyncio.Task[None] | None = field(default=None, init=False)
    _arm_event: asyncio.Event = field(init=False)
    _disarm_event: asyncio.Event = field(init=False)

    def __post_init__(self) -> None:
        async def _make_event() -> tuple[asyncio.Event, asyncio.Event]:
            return asyncio.Event(), asyncio.Event()

        self._arm_event, self._disarm_event = run_coro(_make_event())

    async def ensure_ready(self) -> None:
        await super().ensure_ready()
        self._arm_event.clear()
        self._disarm_event.clear()
        self._pump_task = asyncio.create_task(self._pump())

    async def start_acquiring(self) -> None:
        self._arm_event.set()

    async def wait_for_idle(self) -> None:
        # TODO: what to put here?
        ...

    async def ensure_stopped(self) -> None:
        if self._pump_task is not None:
            self._disarm_event.set()
            await self._pump_task

    @abc.abstractmethod
    async def _pump(self) -> None: ...


@dataclass
class BaseDataLogic(DetectorDataLogic, Loggable):
    writer: DataWriter
    path_provider: PathProvider

    _drain_task: asyncio.Task[None] | None = field(default=None, init=False)
    _drain_ready_event: asyncio.Event = field(init=False)

    def __post_init__(self) -> None:
        async def _make_event() -> asyncio.Event:
            return asyncio.Event()

        self._drain_ready_event = run_coro(_make_event())

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

        self._drain_task = asyncio.create_task(self._drain(datakey_name))

        await self._drain_ready_event.wait()

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
        sig = self.writer.get_counter(datakey_name)
        return StreamResourceDataProvider(
            uri=f"{path_info.directory_path}{path_info.filename}.{extension}",
            resources=[data_resource],
            mimetype=self.writer.mimetype,
            collections_written_signal=sig,
        )

    async def stop(self) -> None:
        if self._drain_task is not None:
            self._drain_task.cancel()
            await self._drain_task

    @abc.abstractmethod
    async def _drain(self, datakey_name: str) -> None: ...
