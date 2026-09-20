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
import re
import sys
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

import numpy as np
from fastcs.attributes import AttributeIO, AttributeIORef, AttrR, AttrRW, AttrW
from fastcs.controllers import Controller
from fastcs.datatypes import Bool, Float, Int, String, Waveform
from fastcs.logging import logger
from fastcs.methods import scan
from pymmcore_plus import CMMCorePlus

from ._process import controller_id, identity_arguments, plain_logging, serve

if TYPE_CHECKING:
    from numpy.typing import NDArray

#: Printed once a client can reach the camera's PVs.
READY: Final = "mmcore camera ready"

#: Seconds between two frames published on ``Buffer``.
LIVE_PERIOD: Final = 0.1

#: Milliseconds, the exposure a camera starts on.
DEFAULT_EXPOSURE: Final = 100.0

#: Seconds the grabbing thread waits when the camera has no frame ready.
EMPTY_POLL: Final = 0.001

#: Seconds between two reads of a Micro-Manager property.
PROPERTY_POLL: Final = 1.0

#: Where the camera's own properties sit under its prefix.
PROPERTY_GROUP: Final = "properties"

#: What a PV name may not carry, replaced by an underscore.
NOT_IN_A_PV_NAME: Final = re.compile(r"[^A-Za-z0-9_]")

#: What ``State`` reads while the camera takes no frames.
IDLE: Final = "idle"

#: What ``State`` reads while the camera takes frames.
ACQUIRING: Final = "acquiring"

#: What ``State`` reads once grabbing stopped on an error.
FAULTED: Final = "faulted"


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
        """Apply *value* to the camera, and read back what it took."""
        match attr.io_ref.setting:
            case "exposure":
                await asyncio.to_thread(self._core.setExposure, float(value))
            case "roi":
                roi = tuple(int(item) for item in value)
                await asyncio.to_thread(lambda: self._core.setROI(*roi))
            case setting:
                raise ValueError(f"no camera setting named {setting!r}")
        if isinstance(attr, AttrR):
            # without this the readback carries the old value until the next
            # scan, and a client that reads straight after writing sees it
            await self.update(attr)

    async def update(self, attr: AttrR[Any, CoreRef]) -> None:
        """Read the camera's own value of the setting into *attr*."""
        match attr.io_ref.setting:
            case "exposure":
                await attr.update(await asyncio.to_thread(self._core.getExposure))
            case "roi":
                roi = await asyncio.to_thread(self._core.getROI)
                await attr.update(np.asarray(roi, dtype=np.int32))
            case setting:
                raise ValueError(f"no camera setting named {setting!r}")


@dataclass
class PropertyRef(AttributeIORef):
    """Names the Micro-Manager property an attribute reads and writes."""

    property: str = ""


class PropertyIO(AttributeIO[str, PropertyRef]):
    """Reads and writes one Micro-Manager property of the camera.

    Every property travels as text, which is how Micro-Manager itself holds
    them; a client that wants a number parses what it reads.
    """

    def __init__(self, core: CMMCorePlus, label: str) -> None:
        super().__init__()
        self._core = core
        self._label = label

    async def send(self, attr: AttrW[str, PropertyRef], value: str) -> None:
        """Write the property, and read back what the camera made of it."""
        await asyncio.to_thread(
            self._core.setProperty, self._label, attr.io_ref.property, value
        )
        if isinstance(attr, AttrR):
            await self.update(attr)

    async def update(self, attr: AttrR[str, PropertyRef]) -> None:
        """Read the camera's own value of the property."""
        value = await asyncio.to_thread(
            self._core.getProperty, self._label, attr.io_ref.property
        )
        await attr.update(str(value))


class FrameStore:
    """The Zarr store a capture window writes its frames to."""

    def __init__(self, uri: str, data_key: str, frame: NDArray[Any]) -> None:
        import acquire_zarr as az

        # a store with an output key and no downsampling is a plain Zarr array,
        # which is what a median written beside these frames needs
        array = az.ArraySettings()
        array.output_key = data_key
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
    state = AttrR(String())
    last_error = AttrR(String())

    def __init__(self, core: CMMCorePlus, label: str, data_key: str) -> None:
        self._property_io = PropertyIO(core, label)
        super().__init__(ios=[CoreIO(core), self._property_io])
        self._core = core
        self._label = label
        self._default_data_key = data_key
        self._latest: NDArray[Any] | None = None
        self._grabbed = 0
        self._published = 0
        self._written = 0
        self._window_full = False
        self._store: FrameStore | None = None
        self._writing = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._grabbing = threading.Event()
        self._stopped = threading.Event()
        self._stopped.set()
        self._grabber: asyncio.Task[None] | None = None
        self._sequencing = False
        self._error: str | None = None

        self.acquire.add_on_update_callback(self._on_acquire)
        self.capture.add_on_update_callback(self._on_capture)

    async def initialise(self) -> None:
        """Declare the frame buffer, whose shape and dtype the camera decides."""
        self._loop = asyncio.get_running_loop()
        frame = await asyncio.to_thread(self.grab_once)
        if frame is None:
            raise RuntimeError("the camera gave no frame to size the buffer from")
        self.buffer = AttrR(Waveform(frame.dtype, shape=frame.shape))
        await self.pixel_dtype.update(frame.dtype.name)
        await self.data_key.update(self._default_data_key)
        self.add_sub_controller(PROPERTY_GROUP, await self._build_properties())

    async def _build_properties(self) -> Controller:
        """Publish every property the camera lets a client write.

        Which properties a camera has is known only once it is loaded, so the
        attributes are built here rather than declared on the class. Read-only
        properties are left out: a client can change nothing about them.
        """
        names = await asyncio.to_thread(self._core.getDevicePropertyNames, self._label)
        read_only = await asyncio.to_thread(
            lambda: {
                name: self._core.isPropertyReadOnly(self._label, name) for name in names
            }
        )
        properties = Controller(ios=[self._property_io])
        for name in names:
            if read_only[name]:
                continue
            # a PV name takes no spaces or brackets, and Micro-Manager's do
            # ("Photon Conversion Factor"): the attribute is named for the PV,
            # the reference keeps the name the camera answers to
            attribute = NOT_IN_A_PV_NAME.sub("_", name)
            if attribute in properties.attributes:
                logger.warning(f"Property {name!r} clashes with {attribute!r}, skipped")
                continue
            setattr(
                properties,
                attribute,
                AttrRW(
                    String(),
                    io_ref=PropertyRef(property=name, update_period=PROPERTY_POLL),
                ),
            )
        return properties

    async def disconnect(self) -> None:
        """Stop grabbing and finish a capture left open."""
        await self._stop_grabbing()
        self._close_store()

    @scan(LIVE_PERIOD)
    async def publish_frame(self) -> None:
        """Publish the latest frame and what the capture has written.

        A client waits for ``FrameCount`` to advance to know its frame is
        newer than the move it just made, so the count is of frames the
        camera took, and a tick with no new frame publishes nothing.
        """
        await self._publish_state()
        grabbed = self._grabbed
        frame = self._latest
        if frame is None or grabbed == self._published:
            return
        self._published = grabbed
        await self.buffer.update(frame)
        await self.frame_count.update(grabbed)
        if self.captured.get() != self._written:
            await self.captured.update(self._written)

    async def reconnect(self) -> None:
        """Forget the last error and grab again if the camera should be."""
        self._error = None
        await super().reconnect()
        if self.acquire.get():
            self._start_grabbing()

    async def _publish_state(self) -> None:
        """Report what the camera is doing and what stopped it, if anything."""
        error = self._error
        if error is not None and self.last_error.get() != error:
            await self.last_error.update(error)
        if error is not None:
            state = FAULTED
        elif self._grabbing.is_set():
            state = ACQUIRING
        else:
            state = IDLE
        if self.state.get() != state:
            await self.state.update(state)

    async def _on_acquire(self, acquiring: bool) -> None:
        """Start or stop the thread grabbing frames."""
        if acquiring:
            self._start_grabbing()
        else:
            await self._stop_grabbing()

    def wait_until_idle(self, timeout: float | None = None) -> bool:
        """Block until no thread is grabbing, and say whether one still is.

        The thread ends when ``Acquire`` is cleared and when the camera
        fails, so this is what tells a caller a fault has been recorded.
        """
        return self._stopped.wait(timeout)

    def _start_grabbing(self) -> None:
        """Put the grabbing thread to work, unless it already is."""
        if self._grabber is not None and not self._grabber.done():
            return
        self._grabbing.set()
        self._stopped.clear()
        self._grabber = asyncio.create_task(asyncio.to_thread(self._grab_loop))

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
        self._window_full = False
        self._store = FrameStore(self.file_path.get(), self.data_key.get(), frame)

    async def _end_capture(self) -> None:
        """Finish a window that has written every frame it was asked for."""
        self._close_store()
        await self.captured.update(self._written)
        await self.capture.update(False)

    async def _stop_grabbing(self) -> None:
        """Ask the grabbing thread to end, and wait for it."""
        self._grabbing.clear()
        if self._grabber is not None:
            await self._grabber
            self._grabber = None

    def _close_store(self) -> None:
        """Finish the capture's store, if one is open.

        Under the lock the grabbing thread appends beneath: a store closed
        between its check and its append would be written to after the stream
        behind it is finished.
        """
        with self._writing:
            if self._store is not None:
                self._store.close()
                self._store = None

    def take_frame(self) -> NDArray[Any] | None:
        """Return the camera's next frame, or ``None`` while it has none.

        A running sequence fills Micro-Manager's circular buffer, and a frame
        is taken from there; without one, each call exposes the camera itself.
        """
        if not self._sequencing:
            return self._core.snap()
        if self._core.getRemainingImageCount() < 1:
            return None
        return self._core.popNextImage()

    def grab_once(self) -> NDArray[Any] | None:
        """Take one frame, and write it if a capture window wants it.

        Runs in the grabbing thread. The store is opened and closed on the
        event loop, so this only ever appends to one: on the last frame of a
        bounded window it hands the closing back through ``_end_capture``.
        """
        frame = self.take_frame()
        if frame is None:
            return None
        self._latest = frame
        self._grabbed += 1

        with self._writing:
            store = self._store
            if store is None or self._window_full:
                return frame
            store.append(frame)
            self._written += 1
            wanted = self.num_capture.get()
            if wanted and self._written >= wanted:
                self._window_full = True
                self._finish_window()
        return frame

    def _finish_window(self) -> None:
        """Ask the event loop to close the window this thread has filled."""
        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(self._end_capture(), self._loop)

    def _grab_loop(self) -> None:
        """Take frames until asked to stop, or until the camera fails."""
        try:
            self._start_sequence()
            while self._grabbing.is_set():
                if self.grab_once() is None:
                    time.sleep(EMPTY_POLL)
        except Exception as error:  # noqa: BLE001
            self._error = f"{type(error).__name__}: {error}"
            self._grabbing.clear()
            # a client waits for Capture to fall to know its window is over,
            # and no frame will arrive to end it now
            self._finish_window()
        finally:
            self._stop_sequence()
            self._stopped.set()

    def _start_sequence(self) -> None:
        """Ask the camera for a continuous sequence, and note whether it took.

        An adapter that refuses one leaves ``take_frame`` exposing per frame,
        which is slower but works everywhere.
        """
        try:
            self._core.startContinuousSequenceAcquisition(0)
        except Exception as error:  # noqa: BLE001
            logger.warning(f"Camera refused a sequence, exposing per frame: {error}")
            self._sequencing = False
            return
        self._sequencing = True

    def _stop_sequence(self) -> None:
        """End the sequence the camera is running, if it is running one."""
        if not self._sequencing:
            return
        self._sequencing = False
        self._core.stopSequenceAcquisition()


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
    return MMCameraController(core, label, data_key)


def main(argv: list[str] | None = None) -> int:
    """Run the service, taking its identity from the session that launched it."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", required=True, help="Micro-Manager adapter")
    parser.add_argument("--device", required=True, help="device of that adapter")
    identity_arguments(parser, "camera")
    options = parser.parse_args(argv)

    plain_logging()
    controller = build_controller(
        options.adapter, options.device, options.name, options.name
    )
    asyncio.run(serve(controller, controller_id(options), READY))
    return 0


if __name__ == "__main__":
    sys.exit(main())
