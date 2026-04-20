from __future__ import annotations

import asyncio
from dataclasses import dataclass
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
from redsun.storage import SourceInfo

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ophyd_async.core import PathProvider, SignalRW
    from ophyd_async.core._data_providers import StreamableDataProvider
    from pymmcore_plus import CMMCorePlus as Core
    from redsun.storage import DataWriter

    from ._backend import ROIType


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
class MMArmLogic(DetectorArmLogic):
    """DetectorArmLogic for a pymmcore-plus camera device."""

    datakey_name: str
    core: Core
    writer: DataWriter

    async def arm(self) -> None:
        """Open the zarr store (if not already open) then start MM sequence acquisition."""
        if not self.writer.is_open:
            self.writer.open()
        self.core.startContinuousSequenceAcquisition()

    async def wait_for_idle(self) -> None:
        """Poll until the sequence acquisition finishes."""
        ...

    async def disarm(self, on_unstage: bool) -> None:
        self.core.stopSequenceAcquisition()
        if self.writer.is_open:
            self.writer.unregister(self.datakey_name)
            if len(self.writer.sources) == 0:
                self.writer.close()


@dataclass
class MMDataLogic(DetectorDataLogic):
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
