from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import numpy as np
from ophyd_async.core import (
    AsyncStatus,
    DetectorAcquireLogic,
    DetectorDataLogic,
    DetectorTriggerLogic,
    SignalR,
    SignalRW,
    StandardDetector,
    StreamResourceDataProvider,
    StreamResourceInfo,
    TriggerInfo,
    wait_for_value,
)
from ophyd_async.fastcs.core import fastcs_connector
from redsun.log import Loggable

from redsun_mimir.device.containers import ReadableDeviceMap  # noqa: TC001
from redsun_mimir.roi import Roi

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bluesky.protocols import Reading
    from event_model import DataKey
    from ophyd_async.core import PathProvider, StreamableDataProvider

#: What a capture window writes, as the documents name it.
MIMETYPE = "application/x-zarr"

#: Seconds ``trigger`` waits for a frame taken after it was called.
DEFAULT_TIMEOUT: Final = 5.0

#: Milliseconds per second, the units a camera takes its exposure in.
MILLISECONDS = 1000.0

#: What the service reports as its state once grabbing stopped on an error.
FAULTED: Final = "faulted"


@dataclass
class ServiceTriggerLogic(DetectorTriggerLogic):
    """Tells the camera service how many frames the next window writes."""

    camera: MMCamera

    def config_sigs(self) -> set[SignalR[Any]]:
        """Return the settings that describe how the frames were taken."""
        return {
            self.camera.exposure,
            self.camera.roi,
            self.camera.pixel_dtype,
            self.camera.sensor_size,
        }

    async def prepare_internal(
        self, num: int, livetime: float, deadtime: float
    ) -> None:
        """Set the exposure and the number of frames to write, 0 for unbounded."""
        if livetime:
            await self.camera.exposure.set(livetime * MILLISECONDS)
        await self.camera.num_capture.set(num)

    async def default_trigger_info(self) -> TriggerInfo:
        """Return the unbounded window a plan without `prepare` gets."""
        return TriggerInfo(number_of_events=0)


@dataclass
class ServiceAcquireLogic(DetectorAcquireLogic):
    """Starts and stops the camera and the window it writes.

    The camera takes frames from ``stage`` to ``unstage``, whether or not
    anything is being written: a viewer watching the buffer needs them, and a
    read after a move reads the frame that arrived since.
    """

    camera: MMCamera

    async def ensure_ready(self) -> None:
        """Have the camera take frames."""
        await self.camera.acquire.set(True)

    async def start_acquiring(self) -> None:
        """Open the window frames are written to."""
        await self.camera.capture.set(True)

    async def wait_for_idle(self) -> None:
        """Wait for a bounded window to write its last frame, or end an unbounded one.

        Closing an unbounded window here, rather than at unstage, is what
        makes the count the documents report the count of frames on disk.
        """
        if await self.camera.num_capture.get_value():
            closed = asyncio.ensure_future(
                wait_for_value(self.camera.capture, False, timeout=None)
            )
            faulted = asyncio.ensure_future(
                wait_for_value(self.camera.state, FAULTED, timeout=None)
            )
            try:
                await asyncio.wait(
                    [closed, faulted], return_when=asyncio.FIRST_COMPLETED
                )
            finally:
                closed.cancel()
                faulted.cancel()
            await self.camera.faulted()
        else:
            await self.camera.capture.set(False)

    async def ensure_stopped(self) -> None:
        """Close the window and stop the camera."""
        await self.camera.capture.set(False)
        await self.camera.acquire.set(False)


@dataclass
class ServiceDataLogic(DetectorDataLogic):
    """Names the store the camera service writes, and reports what it wrote."""

    camera: MMCamera
    path_provider: PathProvider

    def get_hinted_fields(self, datakey_name: str) -> Sequence[str]:
        """Return the stream a viewer plots by default."""
        return [datakey_name]

    async def prepare_unbounded(self, datakey_name: str) -> StreamableDataProvider:
        """Hand the service a store to write, and describe what lands in it."""
        info = self.path_provider(datakey_name)
        directory = Path(info.directory_path)
        directory.mkdir(parents=True, exist_ok=True)
        store = directory / f"{info.filename}.zarr"

        await asyncio.gather(
            self.camera.file_path.set(str(store)),
            self.camera.data_key.set(datakey_name),
        )
        # the service starts its count over when it is handed a store, and
        # what is counted from here is what this window writes
        await wait_for_value(self.camera.captured, 0, timeout=DEFAULT_TIMEOUT)
        shape, dtype = await frame_shape_and_dtype(self.camera)

        return StreamResourceDataProvider(
            uri=f"{info.directory_uri}{info.filename}.zarr",
            resources=[
                StreamResourceInfo(
                    data_key=datakey_name,
                    shape=shape,
                    chunk_shape=(1, *shape),
                    dtype_numpy=np.dtype(dtype).str,
                    parameters={"dataset": datakey_name},
                )
            ],
            mimetype=MIMETYPE,
            collections_written_signal=self.camera.captured,
        )


async def frame_shape_and_dtype(camera: MMCamera) -> tuple[tuple[int, int], str]:
    """Return the ``(height, width)`` and dtype of the frames a camera sends."""
    text, dtype = await asyncio.gather(
        camera.roi.get_value(), camera.pixel_dtype.get_value()
    )
    roi = Roi.parse(text)
    return (roi.height, roi.width), dtype


class MMCamera(StandardDetector, Loggable):
    """A Micro-Manager camera, reached through the service that owns it.

    The service publishes PVI, so every signal below is built from its
    annotation and paired by name; the adapter and the device belong to the
    service's declaration, not to this one.

    Parameters
    ----------
    prefix :
        PV prefix of the service, ending in ``:``. A device declared with
        ``service=`` receives it from that service.
    path_provider :
        Where a capture window writes. The session passes its own.
    """

    # the filler reads these annotations at runtime to build the signals, so
    # the types they name are imported at runtime too. The settings a reading
    # is described by are registered by the trigger logic, since a detector is
    # not a StandardReadable and cannot carry the annotation
    exposure: SignalRW[float]
    roi: SignalRW[str]
    pixel_dtype: SignalR[str]
    sensor_size: SignalR[np.ndarray]
    buffer: SignalR[np.ndarray]
    acquire: SignalRW[bool]
    frame_count: SignalR[int]
    capture: SignalRW[bool]
    file_path: SignalRW[str]
    data_key: SignalRW[str]
    num_capture: SignalRW[int]
    captured: SignalR[int]
    state: SignalR[str]
    last_error: SignalR[str]
    properties: ReadableDeviceMap[SignalRW[str]]

    def __init__(
        self, prefix: str, *, path_provider: PathProvider, name: str = ""
    ) -> None:
        super().__init__(name=name, connector=fastcs_connector(prefix, self))
        self.add_detector_logics(
            ServiceTriggerLogic(self),
            ServiceAcquireLogic(self),
            ServiceDataLogic(self, path_provider),
        )

    async def read_configuration(self) -> dict[str, Reading[Any]]:
        """Return the settings, and every property the camera lets one write."""
        settings, properties = await asyncio.gather(
            super().read_configuration(), self.properties.read()
        )
        return {**settings, **properties}

    async def describe_configuration(self) -> dict[str, DataKey]:
        """Describe the settings, and every property the camera lets one write."""
        settings, properties = await asyncio.gather(
            super().describe_configuration(), self.properties.describe()
        )
        return {**settings, **properties}

    async def faulted(self) -> None:
        """Raise with the camera's own words if it has stopped on a fault.

        A fault ends the grabbing thread, so a wait for its next frame or its
        last one would only time out; this is what names the cause instead.
        """
        if await self.state.get_value() == FAULTED:
            raise RuntimeError(
                f"{self.name} stopped: {await self.last_error.get_value()}"
            )

    @AsyncStatus.wrap
    async def trigger(self) -> None:  # type: ignore[override]
        """Wait for a frame taken after this call.

        The camera takes frames continuously, so the one already published
        may predate the move a plan just made; this waits for the next.
        """
        seen = await self.frame_count.get_value()
        await self.faulted()
        try:
            await wait_for_value(
                self.frame_count, lambda count: count > seen, timeout=DEFAULT_TIMEOUT
            )
        except TimeoutError:
            await self.faulted()
            raise
