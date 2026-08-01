from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, Literal

from ophyd_async.core import (
    DetectorAcquireLogic,
    DetectorDataLogic,
    DetectorTriggerLogic,
    StreamResourceDataProvider,
    TriggerInfo,
)
from redsun.log import Loggable
from redsun.storage import StreamSpec

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ophyd_async.core import SignalRW, StreamableDataProvider
    from redsun.storage import BaseStorage, FrameSink

    from redsun_mimir.protocols import ROIType

AxisType = Literal["x", "y", "z"]

DEFAULT_TIMEOUT: Final[float] = 5.0


async def get_shape_and_dtype(
    roi: SignalRW[ROIType], dtype: SignalRW[str]
) -> tuple[tuple[int, int], str]:
    """Compute a frame's ``(height, width)`` shape and dtype from device signals.

    Parameters
    ----------
    roi : SignalRW[ROIType]
        Signal carrying the current region of interest, ``[x, y, width, height]``.
    dtype : SignalRW[str]
        Signal carrying the current pixel dtype (e.g. ``"uint16"``).
    """
    shape_array, np_dtype = await asyncio.gather(roi.get_value(), dtype.get_value())
    shape = tuple(shape_array.tolist())
    if len(shape) != 4:
        raise ValueError(f"Expected shape array of length 4, got {len(shape)}")
    return (shape[2] - shape[0], shape[3] - shape[1]), np_dtype


@dataclass
class BaseTriggerLogic(DetectorTriggerLogic):
    """Trigger logic registering a stream with the shared storage.

    Stashes the requested frame count on the sibling ``acquire`` logic so
    [`BaseDataLogic`][redsun_mimir.device._logics.BaseDataLogic] can derive
    the same capacity when it registers its `StreamResourceDataProvider`.
    """

    datakey_name: str
    storage: BaseStorage
    acquire: BaseAcquireLogic
    roi: SignalRW[ROIType]
    dtype: SignalRW[str]

    async def prepare_internal(
        self, num: int, livetime: float, deadtime: float
    ) -> None:
        shape, np_dtype = await get_shape_and_dtype(self.roi, self.dtype)
        self.acquire.num = num
        self.storage.register(
            StreamSpec(
                data_key=self.datakey_name,
                shape=shape,
                dtype=np_dtype,
                capacity=num or None,
            )
        )

    async def default_trigger_info(self) -> TriggerInfo:
        return TriggerInfo(number_of_events=0)


@dataclass
class BaseAcquireLogic(DetectorAcquireLogic, Loggable):
    """Shared acquire-logic state for continuous, buffer-fed detectors.

    Frames always flow to the device's buffer signal for viewers; they flow
    into `storage` only while a write window is active - the sink handed over
    at `prepare` (`pending_sink`) becomes live (`sink`) at kickoff
    (`start_acquiring`), so storage never sees a frame it will not write.
    Subclasses provide the hardware polling loop and must implement
    `ensure_ready`/`ensure_stopped` to start and stop it, calling
    `_close_sinks` from `ensure_stopped` once the loop has really stopped.
    """

    num: int = field(default=0, init=False)
    pending_sink: FrameSink | None = field(default=None, init=False)
    sink: FrameSink | None = field(default=None, init=False)

    async def start_acquiring(self) -> None:
        """Activate the write window: the pending sink becomes live."""
        if self.pending_sink is not None:
            self.sink, self.pending_sink = self.pending_sink, None

    async def wait_for_idle(self) -> None:
        return None

    def _close_sinks(self) -> None:
        """Close any live or pending sink. Idempotent."""
        for candidate in (self.sink, self.pending_sink):
            if candidate is not None:
                candidate.close()
        self.sink = None
        self.pending_sink = None


@dataclass
class BaseDataLogic(DetectorDataLogic, Loggable):
    """Data logic building a `StreamResourceDataProvider` from shared storage.

    Parameters
    ----------
    storage : BaseStorage
        Backend this detector writes to.
    acquire : BaseAcquireLogic
        Sibling acquire logic; receives the sink and supplies the capacity
        registered by the sibling trigger logic.
    roi, dtype : SignalRW
        Signals used to derive the frame shape and dtype.
    eager_open : bool
        If True, `open()` the backend at prepare time. Only legal when this
        detector exclusively owns its storage group - a sibling's `register`
        would otherwise race the open and raise `StoreStateError`.
        Shared-storage detectors must pass `False` and rely on the drain's
        lazy open.
    """

    storage: BaseStorage
    acquire: BaseAcquireLogic
    roi: SignalRW[ROIType]
    dtype: SignalRW[str]
    eager_open: bool = True

    def get_hinted_fields(self, datakey_name: str) -> Sequence[str]:
        return [datakey_name]

    async def prepare_unbounded(self, datakey_name: str) -> StreamableDataProvider:
        self.acquire.pending_sink = self.storage.sink(datakey_name)
        if self.eager_open:
            await self.storage.open()
        shape, np_dtype = await get_shape_and_dtype(self.roi, self.dtype)
        spec = StreamSpec(
            data_key=datakey_name,
            shape=shape,
            dtype=np_dtype,
            capacity=self.acquire.num or None,
        )
        return StreamResourceDataProvider(
            uri=self.storage.uri_for(datakey_name),
            resources=[self.storage.resource_info_for(spec)],
            mimetype=self.storage.mimetype,
            collections_written_signal=self.storage.signal_for(datakey_name),
        )
