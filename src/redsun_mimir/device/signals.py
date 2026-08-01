from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import numpy as np
from ophyd_async.core import SignalR, SignalRW, SoftSignalBackend

# SignalDatatypeT parametrises the class below, so it is needed at runtime;
# neither it nor Getter/Setter has a public import path in ophyd-async.
from ophyd_async.core._signal_backend import SignalDatatypeT

from redsun_mimir.device._logics import DEFAULT_TIMEOUT

if TYPE_CHECKING:
    from collections.abc import Callable

    from event_model.documents import DataKey, Limits
    from ophyd_async.core._soft_signal_backend import Getter, Setter

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


class BoundedSoftSignalBackend(SoftSignalBackend[SignalDatatypeT]):
    """SoftSignalBackend that exposes control limits in its DataKey.

    ``limits`` is the one piece of metadata ophyd-async's soft backend cannot
    express (``make_metadata`` covers only units and precision), so this
    subclass stays even for signals that are otherwise plain callables - the
    light view sizes its slider from ``limits.control``.

    ``getter``/``setter``/``poll_period`` are forwarded untouched, so a
    bounded signal can be hardware-backed like any other soft signal.
    """

    def __init__(
        self,
        low: float,
        high: float,
        units: str | None = None,
        initial_value: SignalDatatypeT | None = None,
        *,
        datatype: type[SignalDatatypeT] = float,  # type: ignore[assignment]
        getter: Getter[SignalDatatypeT] | None = None,
        setter: Setter[SignalDatatypeT] | None = None,
        poll_period: float | None = None,
    ) -> None:
        super().__init__(
            datatype,
            initial_value=initial_value,
            units=units,
            getter=getter,
            setter=setter,
            poll_period=poll_period,
        )
        self._low: float = low
        self._high: float = high

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
    initial_value: SignalDatatypeT | None = None,
    *,
    datatype: type[SignalDatatypeT] = float,  # type: ignore[assignment]
    name: str = "bounded_signal",
    getter: Getter[SignalDatatypeT] | None = None,
    setter: Setter[SignalDatatypeT] | None = None,
    poll_period: float | None = None,
) -> SignalRW[SignalDatatypeT]:
    """Create a bounded soft signal with control limits in its DataKey.

    Pass *getter*/*setter* to back the signal with a hardware call; leave
    them out for a purely in-memory bounded value.
    """
    backend = BoundedSoftSignalBackend(
        low,
        high,
        units,
        initial_value,
        datatype=datatype,
        getter=getter,
        setter=setter,
        poll_period=poll_period,
    )
    return SignalRW(backend, name=name, timeout=DEFAULT_TIMEOUT)


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
