"""One Micro-Manager camera, served over PVAccess.

Run as ``python -m redsun_mimir.services.mmcore_camera --adapter DemoCamera
--device DCam``. The PV prefix and the name come from the environment the
``redsun`` session launches it with.

The process owns its own ``CMMCorePlus``, one camera per process, so a
session can run several despite Micro-Manager's one-camera limit.
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

from redsun_mimir.common import Roi

from ._process import controller_id, identity_arguments, serve, session_logging

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable

    from numpy.typing import NDArray

#: Printed once a client can reach the camera's PVs.
READY: Final = "mmcore camera ready"

#: Micro-Manager's ``PixelType`` for each numpy dtype a camera reads out in.
#: Colour types are left out: a frame of one is not a 2D array.
PIXEL_TYPES: Final = {"uint8": "8bit", "uint16": "16bit", "uint32": "32bit"}

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


def as_is(apply: Callable[[], None]) -> None:
    """Run *apply* as it is, for a camera nothing sequences."""
    apply()


class CoreIO(AttributeIO[Any, CoreRef]):
    """Reads and writes camera settings through Micro-Manager.

    *without_sequence* runs a callable with no sequence acquisition running,
    for the settings Micro-Manager refuses during one. *layout_changed* is
    handed a frame snapped after a setting that changes what frames look
    like.
    """

    def __init__(
        self,
        core: CMMCorePlus,
        without_sequence: Callable[[Callable[[], None]], None] = as_is,
        layout_changed: Callable[[NDArray[Any]], Awaitable[None]] | None = None,
    ) -> None:
        super().__init__()
        self._core = core
        self._without_sequence = without_sequence
        self._layout_changed = layout_changed

    async def send(self, attr: AttrW[Any, CoreRef], value: Any) -> None:
        """Apply *value* to the camera, and read back what it took.

        Raises
        ------
        ValueError
            For a pixel dtype the camera does not read out in.
        """
        match attr.io_ref.setting:
            case "exposure":
                await asyncio.to_thread(self._core.setExposure, float(value))
            case "roi":
                roi = Roi.parse(value)
                await asyncio.to_thread(
                    self._without_sequence, lambda: self._core.setROI(*roi)
                )
            case "pixel_dtype":
                await self._set_pixel_dtype(str(value))
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
                await attr.update(str(Roi(*roi)))
            case "pixel_dtype":
                dtype = await asyncio.to_thread(self._pixel_dtype)
                if dtype is not None:
                    await attr.update(dtype)
            case setting:
                raise ValueError(f"no camera setting named {setting!r}")

    def pixel_dtypes(self) -> dict[str, str]:
        """Return the dtypes the camera reads out in, each with its ``PixelType``."""
        label = self._core.getCameraDevice()
        if not self._core.hasProperty(label, "PixelType"):
            return {}
        allowed = set(self._core.getAllowedPropertyValues(label, "PixelType"))
        return {
            dtype: pixel for dtype, pixel in PIXEL_TYPES.items() if pixel in allowed
        }

    def _pixel_dtype(self) -> str | None:
        """Return the dtype of the camera's ``PixelType``, ``None`` for one not mapped."""
        label = self._core.getCameraDevice()
        if not self._core.hasProperty(label, "PixelType"):
            return None
        pixel = self._core.getProperty(label, "PixelType")
        return next((d for d, p in PIXEL_TYPES.items() if p == pixel), None)

    async def _set_pixel_dtype(self, dtype: str) -> None:
        supported = await asyncio.to_thread(self.pixel_dtypes)
        if dtype not in supported:
            raise ValueError(
                f"{dtype!r} is not a pixel dtype this camera reads out in; "
                f"one of {sorted(supported)}"
            )
        label = self._core.getCameraDevice()
        snapped: list[NDArray[Any]] = []

        def apply() -> None:
            self._core.setProperty(label, "PixelType", supported[dtype])
            snapped.append(self._core.snap())

        await asyncio.to_thread(self._without_sequence, apply)
        if self._layout_changed is not None:
            await self._layout_changed(snapped[0])


@dataclass
class PropertyRef(AttributeIORef):
    """Names the Micro-Manager property an attribute reads and writes."""

    property: str = ""


class PropertyIO(AttributeIO[str, PropertyRef]):
    """Reads and writes one Micro-Manager property of the camera.

    Every property travels as text, as Micro-Manager holds it; a client
    wanting a number parses it.
    """

    def __init__(
        self,
        core: CMMCorePlus,
        label: str,
        without_sequence: Callable[[Callable[[], None]], None] = as_is,
        layout_changed: Callable[[NDArray[Any]], Awaitable[None]] | None = None,
    ) -> None:
        super().__init__()
        self._core = core
        self._label = label
        self._without_sequence = without_sequence
        self._layout_changed = layout_changed

    async def send(self, attr: AttrW[str, PropertyRef], value: str) -> None:
        """Write the property, and read back what the camera made of it.

        Every write pauses a running sequence, since some properties,
        binning and pixel type among them, are refused during one. A frame
        is snapped while it is paused and handed to *layout_changed*, since a
        property may change what the camera's frames look like.
        """
        snapped: list[NDArray[Any]] = []

        def apply() -> None:
            self._core.setProperty(self._label, attr.io_ref.property, value)
            snapped.append(self._core.snap())

        await asyncio.to_thread(self._without_sequence, apply)
        if isinstance(attr, AttrR):
            await self.update(attr)
        if self._layout_changed is not None:
            await self._layout_changed(snapped[0])

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
    # text, "x,y,width,height": a client can put a string over PVAccess, and
    # not the array a waveform is served as
    roi = AttrRW(String(), io_ref=CoreRef(setting="roi", update_period=1.0))
    pixel_dtype = AttrRW(
        String(), io_ref=CoreRef(setting="pixel_dtype", update_period=1.0)
    )
    sensor_size = AttrR(Waveform(np.int32, shape=(2,)))
    acquire = AttrRW(Bool())
    frame_count = AttrR(Int())
    capture = AttrRW(Bool())
    file_path = AttrRW(String())
    data_key = AttrRW(String())
    num_capture = AttrRW(Int())
    captured = AttrR(Int())
    state = AttrR(String())
    last_error = AttrR(String())

    def __init__(
        self,
        core: CMMCorePlus,
        label: str,
        data_key: str,
        properties: Iterable[str] | None = None,
    ) -> None:
        self._property_io = PropertyIO(
            core, label, self._without_sequence, self.publish_layout
        )
        super().__init__(
            ios=[
                CoreIO(core, self._without_sequence, self.publish_layout),
                self._property_io,
            ]
        )
        self._core = core
        self._label = label
        self._default_data_key = data_key
        self._properties = None if properties is None else set(properties)
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
        self._sequence_lock = threading.Lock()
        self._error: str | None = None

        self.acquire.add_on_update_callback(self._on_acquire)
        self.capture.add_on_update_callback(self._on_capture)
        self.file_path.add_on_update_callback(self._on_file_path)

    async def initialise(self) -> None:
        """Declare the frame buffer, whose shape and dtype the camera decides.

        The sensor size is read here too, before any ROI crops the camera,
        since a ROI is expressed against it.
        """
        self._loop = asyncio.get_running_loop()
        frame = await asyncio.to_thread(self.grab_once)
        if frame is None:
            raise RuntimeError("the camera gave no frame to size the buffer from")
        self.buffer = AttrR(Waveform(frame.dtype, shape=frame.shape))
        await self.pixel_dtype.update(frame.dtype.name)
        await self.sensor_size.update(
            np.array(
                [self._core.getImageWidth(), self._core.getImageHeight()],
                dtype=np.int32,
            )
        )
        await self.data_key.update(self._default_data_key)
        self.add_sub_controller(PROPERTY_GROUP, await self._build_properties())

    async def _build_properties(self) -> Controller:
        """Publish the camera's writable properties, all of them or the ones chosen.

        The attributes are built here rather than declared on the class, since
        a camera's properties are known only once it is loaded. A chosen name
        the camera does not have, or cannot write, is logged and skipped.
        """
        names: list[str] = list(
            await asyncio.to_thread(self._core.getDevicePropertyNames, self._label)
        )
        read_only = await asyncio.to_thread(
            lambda: {
                name: self._core.isPropertyReadOnly(self._label, name) for name in names
            }
        )
        if self._properties is not None:
            for name in self._properties:
                if name not in names or read_only[name]:
                    logger.warning(
                        f"Property {name!r} is not one the camera lets one write"
                    )
            names = [name for name in names if name in self._properties]
        properties = Controller(ios=[self._property_io])
        for name in names:
            # PixelType is pixel_dtype, in numpy's names
            if read_only[name] or name == "PixelType":
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

        ``FrameCount`` counts frames the camera took, and a tick with no new
        frame publishes nothing, so a client can wait on it for a frame newer
        than its last move.
        """
        await self._publish_state()
        grabbed = self._grabbed
        frame = self._latest
        if frame is None or grabbed == self._published:
            return
        self._published = grabbed
        await self.follow_layout(frame)
        await self.buffer.update(frame)
        await self.frame_count.update(grabbed)
        if self.captured.get() != self._written:
            await self.captured.update(self._written)

    async def follow_layout(self, frame: NDArray[Any]) -> None:
        """Retype ``buffer`` and ``pixel_dtype`` to *frame* when its dtype is new.

        The declared dtype would otherwise cast every frame to the first
        frame's.
        """
        if frame.dtype != self.buffer.datatype.array_dtype:
            self.buffer.update_datatype(
                Waveform(frame.dtype, shape=self.buffer.datatype.shape)
            )
            await self.pixel_dtype.update(frame.dtype.name)

    async def publish_layout(self, frame: NDArray[Any]) -> None:
        """Retype to *frame* and publish it, so a client sees a property's effect at once."""
        await self.follow_layout(frame)
        await self.buffer.update(frame)

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
        """Block until the grabbing thread stops, and return whether it did.

        The thread stops when ``Acquire`` is cleared and when the camera
        fails, so a fault is recorded by the time this returns ``True``.
        """
        return self._stopped.wait(timeout)

    def _start_grabbing(self) -> None:
        """Put the grabbing thread to work, unless it already is."""
        if self._grabber is not None and not self._grabber.done():
            return
        # a fault is what stopped the last thread; starting another is the
        # request to try again, and its state reads so at once
        self._error = None
        self._grabbing.set()
        self._stopped.clear()
        self._grabber = asyncio.create_task(asyncio.to_thread(self._grab_loop))

    async def _on_file_path(self, path: str) -> None:
        """Reset ``Captured``: a client names the store before it opens a window.

        A client waits for ``Captured`` to grow past what it read while
        preparing; left at the last window's total, the next would be waited
        on for twice its frames.
        """
        with self._writing:
            self._written = 0
        await self.captured.update(0)

    async def _on_capture(self, capturing: bool) -> None:
        """Open the store frames are written to, or finish the one open.

        Closing publishes the count too, since an unbounded window ends here.
        """
        if not capturing:
            self._close_store()
            await self.captured.update(self._written)
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

        Held under the lock the grabbing thread appends beneath, so no store
        is closed between its check and its append.
        """
        with self._writing:
            if self._store is not None:
                self._store.close()
                self._store = None

    def take_frame(self) -> NDArray[Any] | None:
        """Return the camera's next frame, or ``None`` while it has none.

        With a sequence running the frame comes from Micro-Manager's circular
        buffer; without one, each call exposes the camera.
        """
        if not self._sequencing:
            return self._core.snap()
        if self._core.getRemainingImageCount() < 1:
            return None
        return self._core.popNextImage()

    def grab_once(self) -> NDArray[Any] | None:
        """Take one frame, and write it if a capture window wants it.

        Runs in the grabbing thread and only appends to the store; on the last
        frame of a bounded window it hands the closing to the event loop
        through ``_end_capture``.
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
            with self._sequence_lock:
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
            with self._sequence_lock:
                self._stop_sequence()
            self._stopped.set()

    def _without_sequence(self, apply: Callable[[], None]) -> None:
        """Run *apply* with no sequence running, and resume one that was.

        The grabbing thread exposes per frame meanwhile. The lock keeps this
        from restarting a sequence the grab loop is ending.
        """
        with self._sequence_lock:
            was_sequencing = self._sequencing
            if was_sequencing:
                self._stop_sequence()
            try:
                apply()
            finally:
                if was_sequencing:
                    self._start_sequence()

    def _start_sequence(self) -> None:
        """Ask the camera for a continuous sequence, and note whether it took.

        An adapter that refuses one leaves ``take_frame`` exposing per frame.
        """
        # the flag leads the camera on the way up and trails it on the way
        # down: the grabbing thread exposes only while the flag is clear,
        # and Micro-Manager refuses an exposure during a sequence
        self._sequencing = True
        try:
            self._core.startContinuousSequenceAcquisition(0)
        except Exception as error:  # noqa: BLE001
            logger.warning(f"Camera refused a sequence, exposing per frame: {error}")
            self._sequencing = False

    def _stop_sequence(self) -> None:
        """End the sequence, if the camera is running one."""
        if not self._sequencing:
            return
        self._core.stopSequenceAcquisition()
        self._sequencing = False


def build_controller(
    adapter: str,
    device: str,
    label: str,
    data_key: str,
    properties: Iterable[str] | None = None,
) -> MMCameraController:
    """Load the camera into a core of this process's own, and wrap it."""
    core = CMMCorePlus()
    core.loadDevice(label, adapter, device)
    core.initializeDevice(label)
    core.setCameraDevice(label)
    core.clearROI()
    core.setExposure(DEFAULT_EXPOSURE)
    return MMCameraController(core, label, data_key, properties)


def main(argv: list[str] | None = None) -> int:
    """Run the service, taking its identity from the session that launched it."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", required=True, help="Micro-Manager adapter")
    parser.add_argument("--device", required=True, help="device of that adapter")
    parser.add_argument(
        "--properties",
        default="",
        help="comma-separated camera properties to publish; none without it",
    )
    identity_arguments(parser, "camera")
    options = parser.parse_args(argv)

    session_logging()
    controller = build_controller(
        options.adapter,
        options.device,
        options.name,
        options.name,
        [name for name in options.properties.split(",") if name],
    )
    asyncio.run(serve(controller, controller_id(options), READY))
    return 0


if __name__ == "__main__":
    sys.exit(main())
