from __future__ import annotations

import asyncio
import threading as th
import time
from typing import TYPE_CHECKING

from ophyd_async.core import (
    TriggerInfo,
)
from redsun.storage.logics import FrameWriterArmLogic, FrameWriterTriggerLogic

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

    import numpy as np
    import numpy.typing as npt
    from ophyd_async.core import SignalRW
    from pymmcore_plus import CMMCorePlus as Core
    from redsun.storage import DataWriter


class MMTriggerLogic(FrameWriterTriggerLogic):
    """Trigger logic that syncs MMCore image dimensions into ``NDArrayInfo`` signals.

    Extends [`FrameWriterTriggerLogic`][redsun.storage.logics.FrameWriterTriggerLogic]
    so that writer registration is handled by the base class.  Before each
    ``prepare_internal`` call the current MMCore image geometry is pushed into
    the shared ``NDArrayInfo`` signals, keeping the registered
    [`SourceInfo`][redsun.storage.SourceInfo] in sync with hardware state.

    Parameters
    ----------
    datakey_name : str
        Key used when registering the source with the writer.
    writer : DataWriter
        Shared data writer.
    shape : SignalRW[np.ndarray[tuple[int, ...], np.dtype[np.uint64]]]
        Signal to sync the current MMCore image geometry as a 4-element array
        of (x, y, height, width).
    dtype : SignalRW[str]
        Signal to sync the current MMCore image data type as a NumPy dtype string.
    core :
        Singleton ``CMMCorePlus`` instance.
    """

    def __init__(
        self,
        datakey_name: str,
        writer: DataWriter,
        shape: SignalRW[np.ndarray[tuple[int, ...], np.dtype[np.uint64]]],
        dtype: SignalRW[str],
        core: Core,
    ) -> None:
        super().__init__(
            datakey_name=datakey_name, writer=writer, shape=shape, numpy_dtype=dtype
        )
        self._core = core
        self._n_frames: int = 0
        self._current_exposure: float = 0.0

    def get_deadtime(self, config_values: Any) -> float:
        """Return zero dead time for MMCore software triggering."""
        return 0.0

    async def prepare_internal(
        self, num: int, livetime: float, deadtime: float
    ) -> None:
        """Sync MMCore geometry into ``NDArrayInfo`` signals, then register the source."""
        await super().prepare_internal(num, livetime, deadtime)
        self._n_frames = num
        self._current_exposure = self._core.getExposure() / 1000.0

    async def default_trigger_info(self) -> TriggerInfo:
        """Return a default trigger info with unlimited events."""
        return TriggerInfo(number_of_events=0)


class MMArmLogic(FrameWriterArmLogic):
    """Arm logic that wraps MMCore acquisition on top of ``FrameWriterArmLogic``.

    Extends [`FrameWriterArmLogic`][redsun.storage.logics.FrameWriterArmLogic]
    so that writer open/close and source registration bookkeeping is handled by
    the base class.  The subclass adds a background streaming thread that reads
    frames from MMCore and forwards them to the writer and the camera's
    ``buffer`` signal.

    Parameters
    ----------
    datakey_name :
        Source key used with the writer and MMCore.
    writer :
        Shared data writer.
    core :
        Singleton ``CMMCorePlus`` instance.
    set_buffer :
        Sync callable (from ``soft_signal_r_and_setter``) that pushes
        each acquired frame into the camera's ``buffer`` signal.
    trigger_logic :
        Shared trigger logic instance; provides ``_n_frames`` and
        ``_current_exposure`` set during ``prepare_internal``.
    """

    def __init__(
        self,
        datakey_name: str,
        writer: DataWriter,
        core: Core,
        set_buffer: Callable[[npt.NDArray[Any]], None],
        trigger_logic: MMTriggerLogic,
    ) -> None:
        super().__init__(datakey_name=datakey_name, writer=writer)
        self._core = core
        self._set_buffer = set_buffer
        self._trigger_logic = trigger_logic
        self._stop_event = th.Event()
        self._stream_task: asyncio.Task[None] | None = None

    async def arm(self) -> None:
        """Open the writer (via base class) and start the MMCore streaming thread."""
        await super().arm()
        self._stop_event.clear()
        self._stream_task = asyncio.create_task(
            asyncio.to_thread(self._stream_sync, self._trigger_logic._n_frames)
        )

    async def disarm(self, on_unstage: bool = False) -> None:
        """Stop the streaming thread then delegate close/unregister to base class."""
        self._stop_event.set()
        if self._stream_task is not None:
            await asyncio.shield(self._stream_task)
            self._stream_task = None
        await super().disarm(on_unstage)

    async def wait_for_idle(self) -> None:
        """Await the streaming task completion."""
        if self._stream_task is not None:
            await self._stream_task

    def _stream_sync(self, frames: int) -> None:
        """Blocking acquisition loop — runs in executor thread.

        Parameters
        ----------
        frames :
            Number of frames to acquire.  ``0`` means stream indefinitely
            until ``disarm()`` sets the stop event.
        """
        current_exposure = self._trigger_logic._current_exposure
        if frames > 0:
            self._core.startSequenceAcquisition(frames, current_exposure, False)
        else:
            self._core.startContinuousSequenceAcquisition(current_exposure)

        frames_written = 0
        last_frame = 0
        while not self._stop_event.is_set():
            if self._core.getRemainingImageCount() > 0:
                img, md = self._core.popNextImageAndMD()
                last_frame = int(md.get("ImageNumber", frames_written))
                self._set_buffer(img)
                self.writer.write(self.datakey_name, img)
                frames_written += 1
                if frames > 0 and frames_written >= frames:
                    break
            else:
                time.sleep(current_exposure or 0.005)
                self._core.stopSequenceAcquisition()

        if frames > 0 and (last_frame + 1) > frames_written:
            # TODO: add warning message here.
            ...
