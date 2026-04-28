from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import numpy as np
from ophyd_async.core import SignalR, SignalRW, SoftSignalBackend

from redsun_mimir.device._common import DEFAULT_TIMEOUT

if TYPE_CHECKING:
    from collections.abc import Callable

    from event_model.documents import DataKey, Limits

    from redsun_mimir.protocols import Array2D, ROIType


class BufferSignalBackend(SoftSignalBackend[np.ndarray]):
    """Backend for a soft signal that holds a 2D image buffer."""

    def __init__(self, roi_sig: SignalRW[ROIType], dtype: SignalRW[str]):
        self._roi = roi_sig
        self._dtype = dtype
        super().__init__(np.ndarray, initial_value=np.zeros((1, 1), dtype=np.uint16))

    async def get_datakey(self, source: str) -> DataKey:
        """Get the data key for this signal."""
        roi, dtype_str = await asyncio.gather(
            self._roi.get_value(), self._dtype.get_value()
        )
        roi_list: list[int] = roi.tolist()
        w, h = tuple(roi_list[2:4])
        dtype = np.dtype(dtype_str).str
        descriptor: DataKey = {
            "dtype": "array",
            "shape": [h, w],
            "source": source,
            "dtype_numpy": dtype,
        }
        return descriptor


class BoundedSoftSignalBackend(SoftSignalBackend[float]):
    """SoftSignalBackend that exposes control limits in its DataKey."""

    def __init__(
        self,
        low: float,
        high: float,
        units: str | None = None,
        initial_value: float = 0.0,
    ) -> None:
        super().__init__(float, initial_value=initial_value, units=units)
        self._low = low
        self._high = high

    async def get_datakey(self, source: str) -> DataKey:
        """Get the data key for this signal, including control limits."""
        dk = await super().get_datakey(source)
        # inject control limits into the DataKey
        limits: Limits = {"control": {"low": self._low, "high": self._high}}
        dk["limits"] = limits
        return dk


def bounded_soft_signal_rw(
    low: float,
    high: float,
    units: str | None = None,
    initial_value: float = 0.0,
) -> SignalRW[float]:
    """Create a bounded soft signal with control limits in its DataKey."""
    backend = BoundedSoftSignalBackend(low, high, units, initial_value)
    signal = SignalRW(backend, name="bounded_signal", timeout=DEFAULT_TIMEOUT)
    return signal


def readable_buffer_signal(
    roi_sig: SignalRW[ROIType], dtype: SignalRW[str]
) -> tuple[SignalR[Array2D], Callable[[Array2D], None]]:
    """Create a read-only Signal for a camera image buffer.

    Parameters
    ----------
    roi_sig: SignalRW[ROIType]
        A signal providing the current ROI of the camera, used to determine the buffer shape.
    dtype: SignalRW[str]
        A signal providing the current data type of the camera image, used to determine the buffer dtype.
    """
    backend = BufferSignalBackend(roi_sig, dtype)
    signal = SignalR(backend, name="buffer", timeout=DEFAULT_TIMEOUT)
    return (signal, backend.set_value)


def writeable_buffer_signal(
    roi_sig: SignalRW[ROIType], dtype: SignalRW[str]
) -> SignalRW[Array2D]:
    """Create a read-write Signal for a camera image buffer.

    Parameters
    ----------
    roi_sig: SignalRW[ROIType]
        A signal providing the current ROI of the camera, used to determine the buffer shape.
    dtype: SignalRW[str]
        A signal providing the current data type of the camera image, used to determine the buffer dtype.
    """
    backend = BufferSignalBackend(roi_sig, dtype)
    signal = SignalRW(backend, name="buffer", timeout=DEFAULT_TIMEOUT)
    return signal
