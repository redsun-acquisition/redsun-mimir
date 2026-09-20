"""One Micro-Manager camera, served over PVAccess.

Run as ``python -m redsun_mimir.services.mmcore_camera --adapter DemoCamera
--device DCam``. The PV prefix and the name come from the environment a
``redsun`` session launches it with, so the session writes them once.

The process owns its own ``CMMCorePlus``: one camera per process, which is
what lifts Micro-Manager's one-camera-at-a-time limit for a session with
several of them.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

import numpy as np
from fastcs.attributes import AttributeIO, AttributeIORef, AttrR, AttrRW, AttrW
from fastcs.control_system import FastCS
from fastcs.controllers import Controller
from fastcs.datatypes import Bool, Float, Int, String, Waveform
from fastcs.logging import logger
from fastcs.methods import scan
from fastcs.transports.epics.pva.transport import EpicsPVATransport
from pymmcore_plus import CMMCorePlus

if TYPE_CHECKING:
    from numpy.typing import NDArray

#: Printed once a client can reach the camera's PVs.
READY: Final = "mmcore camera ready"

#: Seconds between two frames published on ``Buffer``.
LIVE_PERIOD: Final = 0.1

#: Milliseconds, the exposure a camera starts on.
DEFAULT_EXPOSURE: Final = 100.0

#: Where the readiness check looks for the camera it just served.
LOOPBACK: Final = "127.0.0.1"

#: What a line of this process's own logging looks like.
LOG_FORMAT: Final = "{level} {message}"


@dataclass
class CoreRef(AttributeIORef):
    """Names the camera setting an attribute reads and writes."""

    setting: str = ""


class CoreIO(AttributeIO[Any, CoreRef]):
    """Reads and writes camera settings through Micro-Manager."""

    def __init__(self, core: CMMCorePlus) -> None:
        super().__init__()
        self._core = core

    async def send(self, attr: AttrW[Any, CoreRef], value: Any) -> None:
        """Apply *value* to the camera."""
        match attr.io_ref.setting:
            case "exposure":
                self._core.setExposure(float(value))
            case "roi":
                self._core.setROI(*(int(item) for item in value))
            case setting:
                raise ValueError(f"no camera setting named {setting!r}")

    async def update(self, attr: AttrR[Any, CoreRef]) -> None:
        """Read the camera's own value of the setting into *attr*."""
        match attr.io_ref.setting:
            case "exposure":
                await attr.update(self._core.getExposure())
            case "roi":
                await attr.update(np.asarray(self._core.getROI(), dtype=np.int32))
            case setting:
                raise ValueError(f"no camera setting named {setting!r}")


class FrameStore:
    """The Zarr store a capture window writes its frames to."""

    def __init__(self, uri: str, data_key: str, frame: NDArray[Any]) -> None:
        import acquire_zarr as az

        array = az.ArraySettings()
        array.output_key = data_key
        array.is_ngff = False
        array.data_type = getattr(az.DataType, frame.dtype.name.upper())
        array.dimensions = [
            az.Dimension(
                name="t",
                kind=az.DimensionType.TIME,
                array_size_px=0,
                chunk_size_px=1,
                shard_size_chunks=1,
            ),
            *(
                az.Dimension(
                    name=name,
                    kind=az.DimensionType.SPACE,
                    array_size_px=size,
                    chunk_size_px=size,
                    shard_size_chunks=1,
                )
                for name, size in zip("yx", frame.shape, strict=True)
            ),
        ]

        settings = az.StreamSettings()
        settings.store_path = uri
        settings.overwrite = False
        settings.arrays = [array]

        self._data_key = data_key
        self._stream = az.ZarrStream(settings)

    def append(self, frame: NDArray[Any]) -> None:
        """Add one frame to the store."""
        self._stream.append(frame[None], self._data_key)

    def close(self) -> None:
        """Finish the store, so what was written can be read."""
        self._stream.close()


class MMCameraController(Controller):
    """A camera's settings, its latest frame, and the capture it writes."""

    exposure = AttrRW(Float(), io_ref=CoreRef(setting="exposure", update_period=1.0))
    roi = AttrRW(
        Waveform(np.int32, shape=(4,)),
        io_ref=CoreRef(setting="roi", update_period=1.0),
    )
    pixel_dtype = AttrR(String())
    acquire = AttrRW(Bool())
    frame_count = AttrR(Int())
    capture = AttrRW(Bool())
    file_path = AttrRW(String())
    data_key = AttrRW(String())
    num_capture = AttrRW(Int())
    captured = AttrR(Int())

    def __init__(self, core: CMMCorePlus, data_key: str) -> None:
        super().__init__(ios=[CoreIO(core)])
        self._core = core
        self._default_data_key = data_key
        self._latest: NDArray[Any] | None = None
        self._published = 0
        self._written = 0
        self._store: FrameStore | None = None
        self._grabbing = threading.Event()
        self._grabber: asyncio.Task[None] | None = None

        self.acquire.add_on_update_callback(self._on_acquire)
        self.capture.add_on_update_callback(self._on_capture)

    async def initialise(self) -> None:
        """Declare the frame buffer, whose shape and dtype the camera decides."""
        frame = await asyncio.to_thread(self._core.snap)
        self._latest = frame
        self.buffer = AttrR(Waveform(frame.dtype, shape=frame.shape))
        await self.pixel_dtype.update(frame.dtype.name)
        await self.data_key.update(self._default_data_key)

    async def disconnect(self) -> None:
        """Stop grabbing and finish a capture left open."""
        await self._stop_grabbing()
        self._close_store()

    @scan(LIVE_PERIOD)
    async def publish_frame(self) -> None:
        """Publish the latest frame and what the capture has written.

        A client waits for ``FrameCount`` to advance to know its frame is
        newer than the move it just made, so the count is of frames
        published here, not of frames the camera took.
        """
        frame = self._latest
        if frame is None:
            return
        self._published += 1
        await self.buffer.update(frame)
        await self.frame_count.update(self._published)
        if self.captured.get() != self._written:
            await self.captured.update(self._written)
        if self._store is None and self.capture.get():
            await self.capture.update(False)

    async def _on_acquire(self, acquiring: bool) -> None:
        """Start or stop the thread grabbing frames."""
        if acquiring:
            if self._grabber is None:
                self._grabbing.set()
                self._grabber = asyncio.create_task(asyncio.to_thread(self._grab_loop))
        else:
            await self._stop_grabbing()

    async def _on_capture(self, capturing: bool) -> None:
        """Open the store frames are written to, or finish the one open."""
        if not capturing:
            self._close_store()
            return
        if self._store is not None:
            return
        frame = self._latest
        if frame is None:
            raise RuntimeError("the camera has taken no frame to size the store from")
        self._written = 0
        self._store = FrameStore(self.file_path.get(), self.data_key.get(), frame)

    async def _stop_grabbing(self) -> None:
        """Ask the grabbing thread to end, and wait for it."""
        self._grabbing.clear()
        if self._grabber is not None:
            await self._grabber
            self._grabber = None

    def _close_store(self) -> None:
        """Finish the capture's store, if one is open."""
        if self._store is not None:
            self._store.close()
            self._store = None

    def _grab_loop(self) -> None:
        """Take frames until asked to stop, writing each one a capture wants.

        ``snap`` rather than Micro-Manager's sequence API, which some adapters
        do not drive correctly alongside other devices.
        """
        while self._grabbing.is_set():
            frame = self._core.snap()
            self._latest = frame
            store = self._store
            if store is None:
                continue
            store.append(frame)
            self._written += 1
            wanted = self.num_capture.get()
            if wanted and self._written >= wanted:
                self._close_store()


def build_controller(
    adapter: str, device: str, label: str, data_key: str
) -> MMCameraController:
    """Load the camera into a core of this process's own, and wrap it."""
    core = CMMCorePlus()
    core.loadDevice(label, adapter, device)
    core.initializeDevice(label)
    core.setCameraDevice(label)
    core.clearROI()
    core.setExposure(DEFAULT_EXPOSURE)
    return MMCameraController(core, data_key)


async def announce_when_reachable(prefix: str) -> None:
    """Print the readiness line once the camera's PVI record answers.

    The session tells its own process where to search, not this one, so the
    check looks on the interface the camera serves.
    """
    from p4p.client.asyncio import Context

    with Context("pva", conf={"EPICS_PVA_ADDR_LIST": LOOPBACK}) as client:
        while True:
            try:
                await asyncio.wait_for(client.get(f"{prefix}:PVI"), timeout=1.0)
            except TimeoutError:
                continue
            break
    print(READY, flush=True)


async def serve(controller: MMCameraController, prefix: str) -> None:
    """Serve the camera until this process's standard input closes."""
    control_system = FastCS(controller, [EpicsPVATransport()])
    controller.set_path([prefix])
    serving = asyncio.ensure_future(control_system.serve(interactive=False))
    announcing = asyncio.ensure_future(announce_when_reachable(prefix))

    await asyncio.to_thread(sys.stdin.read)

    announcing.cancel()
    serving.cancel()
    await asyncio.gather(serving, announcing, return_exceptions=True)


def main(argv: list[str] | None = None) -> int:
    """Run the service, taking its identity from the session that launched it."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", required=True, help="Micro-Manager adapter")
    parser.add_argument("--device", required=True, help="device of that adapter")
    parser.add_argument(
        "--prefix",
        default=os.environ.get("REDSUN_SERVICE_PREFIX", ""),
        help="PV prefix, REDSUN_SERVICE_PREFIX unless given",
    )
    parser.add_argument(
        "--name",
        default=os.environ.get("REDSUN_SERVICE_NAME", "camera"),
        help="name of this service, REDSUN_SERVICE_NAME unless given",
    )
    options = parser.parse_args(argv)

    # the session reads this process's output line by line, and the colours
    # FastCS writes by default would reach its log file as escape sequences
    logger.remove()
    logger.add(sys.stdout, colorize=False, level="INFO", format=LOG_FORMAT)

    prefix = options.prefix.rstrip(":") or options.name
    controller = build_controller(
        options.adapter, options.device, options.name, options.name
    )
    asyncio.run(serve(controller, prefix))
    return 0


if __name__ == "__main__":
    sys.exit(main())
