"""The services: their controllers, and the processes a session launches."""

from __future__ import annotations

import asyncio
import threading
import time
from queue import Queue
from typing import TYPE_CHECKING, Any, cast

import msgspec
import numpy as np
import pytest
from redsun.services import Service

from redsun_mimir.common import Roi
from redsun_mimir.device.youseetoo import UC2LaserDevice, UC2MotorDevice
from redsun_mimir.services import uc2_controller
from redsun_mimir.services.mmcore_camera import MMCameraController, uncrop
from redsun_mimir.services.uc2_controller import UC2Controller

from .conftest import CAMERA_PREFIX, needs_mm_adapters

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Sequence
    from pathlib import Path

    from fastcs.datatypes import Enum
    from numpy.typing import NDArray

PREFIX = CAMERA_PREFIX.rstrip(":")
CAPTURED_FRAMES = 4
TIMEOUT = 30.0
DATA_KEY = "cam"
LABEL = "cam"
FRAME_SHAPE = (4, 6)


class FakeBoard:
    """A YouSeeToo board that acknowledges whatever it is sent.

    The real one answers a move with an acknowledgement and then a stepper
    report, a laser command with an acknowledgement alone, and a position
    query with the state of every stepper it carries, framed in ``++`` and
    ``--``.
    """

    def __init__(self, positions: dict[int, int] | None = None) -> None:
        self.written: list[bytes] = []
        self.is_open = True
        #: where each stepper stands, in steps, as the board keeps it
        self.positions = positions if positions is not None else {}
        self._answers: list[bytes] = []

    def reset_input_buffer(self) -> None:
        pass

    def write(self, packet: bytes) -> int:
        self.written.append(packet)
        request = msgspec.json.decode(packet)
        if request.get("task") == "/motor_get":
            report = msgspec.json.encode(
                {
                    "motor": {
                        "steppers": [
                            {"stepperid": stepper, "position": position}
                            for stepper, position in sorted(self.positions.items())
                        ]
                    },
                    "qid": 0,
                }
            )
            self._answers.append(b"++\r\n" + report + b"\r\n--")
            return len(packet)
        qid = request["qid"]
        self._answers.append(b'{"success": 1, "qid": %d}--' % qid)
        if "motor" in request:
            self._answers.append(b'{"steppers": [], "qid": %d}--' % qid)
        return len(packet)

    def read_until(self, expected: bytes = b"") -> bytes:
        return self._answers.pop(0) if self._answers else b""

    def close(self) -> None:
        self.is_open = False


class FakeCore:
    """A camera whose frames the test takes one at a time.

    Every frame carries the number of the call that produced it, so a test can
    tell one from the next.
    """

    def __init__(self, *, sequences: bool = True) -> None:
        self.snapped = 0
        self.popped = 0
        self.exposure = 100.0
        self.roi: tuple[int, ...] = (0, 0, FRAME_SHAPE[1], FRAME_SHAPE[0])
        self.threads: list[str] = []
        self.properties = {
            "Gain": "0",
            "Photon Flux": "1",
            "CameraName": "fake",
            "PixelType": "8bit",
        }
        self.sequences = sequences
        self.sequencing = False
        self.fault: Exception | None = None
        self.read_mid_sequence: list[str] = []
        self.read_unguarded: list[str] = []
        #: whether a read is safe from a sequence starting under it
        self.guarded: Callable[[], bool] = lambda: True
        self.popped_a_frame = threading.Event()
        #: set while an exposure is in flight, for a layout change to catch
        self.exposing = threading.Event()
        #: an exposure returns only once this is set
        self.may_expose = threading.Event()
        self.may_expose.set()
        #: every layout change the fake was asked for during an exposure
        self.overlapped: list[str] = []
        self._buffer: Queue[NDArray[Any]] = Queue()

    def produce(self, frames: int = 1) -> None:
        """Put *frames* into the circular buffer, as the camera would."""
        for _ in range(frames):
            self._buffer.put(np.full(FRAME_SHAPE, self.popped + 1, dtype=np.uint8))

    def snap(self) -> NDArray[Any]:
        if self.sequencing:
            raise RuntimeError("cannot expose while a sequence acquisition runs")
        self.exposing.set()
        try:
            self.may_expose.wait(TIMEOUT)
            self.snapped += 1
            return np.full(FRAME_SHAPE, self.snapped, dtype=self.dtype)
        finally:
            self.exposing.clear()

    @property
    def dtype(self) -> np.dtype[Any]:
        return np.dtype(
            {"8bit": "uint8", "16bit": "uint16"}[self.properties["PixelType"]]
        )

    def getCameraDevice(self) -> str:
        return LABEL

    def hasProperty(self, label: str, name: str) -> bool:
        return name in self.properties

    def getAllowedPropertyValues(self, label: str, name: str) -> tuple[str, ...]:
        return ("8bit", "16bit") if name == "PixelType" else ()

    def startContinuousSequenceAcquisition(self, interval: float = 0) -> None:
        if not self.sequences:
            raise RuntimeError("this adapter takes no sequence")
        self.sequencing = True

    def stopSequenceAcquisition(self) -> None:
        self.sequencing = False

    def getRemainingImageCount(self) -> int:
        if self.fault is not None:
            raise self.fault
        return self._buffer.qsize()

    def popNextImage(self) -> NDArray[Any]:
        frame = self._buffer.get_nowait()
        self.popped += 1
        self.popped_a_frame.set()
        return frame

    def getDevicePropertyNames(self, label: str) -> tuple[str, ...]:
        return tuple(self.properties)

    def isPropertyReadOnly(self, label: str, name: str) -> bool:
        return name == "CameraName"

    def getProperty(self, label: str, name: str) -> str:
        if self.sequencing:
            # the DahengGalaxy adapter stops delivering when PixelType is read
            # during a sequence; the fake records every such read so a test
            # can pin that none is taken
            self.read_mid_sequence.append(name)
        if not self.guarded():
            self.read_unguarded.append(name)
        return self.properties[name]

    def setProperty(self, label: str, name: str, value: str) -> None:
        if self.sequencing:
            raise RuntimeError("Cannot set property while a sequence runs")
        self.properties[name] = str(value)

    def getExposure(self) -> float:
        self.threads.append(threading.current_thread().name)
        return self.exposure

    def setExposure(self, exposure: float) -> None:
        self.threads.append(threading.current_thread().name)
        self.exposure = exposure

    def getROI(self) -> Sequence[int]:
        return self.roi

    def clearROI(self) -> None:
        self._layout_change("clearROI")
        # the DahengGalaxy adapter writes the size before the offsets, so one
        # clear zeroes the offsets and leaves the size they allowed
        self.roi = (0, 0, FRAME_SHAPE[1] - self.roi[0], FRAME_SHAPE[0] - self.roi[1])

    def setROI(self, *roi: int) -> None:
        self._layout_change("setROI")
        if self.sequencing:
            raise RuntimeError("Cannot set ROI while a sequence runs")
        _, _, width, height = roi
        # a GenICam camera caps the width at what is left of the sensor
        # beyond the current offset, as the DahengGalaxy adapter does and the
        # DemoCamera adapter does not
        room = (FRAME_SHAPE[1] - self.roi[0], FRAME_SHAPE[0] - self.roi[1])
        if width > room[0] or height > room[1]:
            raise RuntimeError(
                f"Value = {max(width, height)} must be equal or smaller "
                f"than Max = {min(room)}"
            )
        self.roi = tuple(roi)

    def _layout_change(self, call: str) -> None:
        """Record *call* if it reached the camera during an exposure."""
        if self.exposing.is_set():
            self.overlapped.append(call)

    def getImageWidth(self) -> int:
        return self.roi[2]

    def getImageHeight(self) -> int:
        return self.roi[3]


async def until(
    predicate: Callable[[], bool], camera: MMCameraController, timeout: float = TIMEOUT
) -> None:
    """Publish ticks until *predicate* holds, or fail the test."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        await camera.publish_frame()
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"timed out after {timeout} s")


@pytest.fixture
async def controller() -> AsyncGenerator[tuple[MMCameraController, FakeCore], None]:
    """Return a controller on a fake camera, brought up as ``FastCS`` does."""
    core = FakeCore()
    controller = MMCameraController(core, LABEL, DATA_KEY)  # type: ignore[arg-type]
    await controller.initialise()
    controller.post_initialise()
    yield controller, core
    await controller.disconnect()


@needs_mm_adapters
def test_the_service_serves_a_camera_and_captures_what_it_grabs(
    camera_service: Service, tmp_path: Path
) -> None:
    """One capture window, from the client's side.

    Reading and writing a setting, watching frames arrive, and writing four of
    them to a store the client named, which is what a session's camera device
    does over the same PVs.
    """
    p4p = pytest.importorskip("p4p.client.thread")
    store = tmp_path / "capture.zarr"

    with p4p.Context("pva") as client:
        client.get(f"{PREFIX}:PVI", timeout=30.0)
        client.put(f"{PREFIX}:Exposure", 25.0, timeout=10.0)
        client.put(f"{PREFIX}:Acquire", True, timeout=10.0)
        client.put(f"{PREFIX}:FilePath", str(store), timeout=10.0)
        client.put(f"{PREFIX}:NumCapture", CAPTURED_FRAMES, timeout=10.0)
        window_over = threading.Event()
        capturing: list[bool] = []

        def on_capture(value: Any) -> None:
            # a monitor hands over a disconnection as an exception, not a value
            if isinstance(value, Exception):
                return
            if bool(value):
                capturing.append(True)
            elif capturing:
                window_over.set()

        watching = client.monitor(f"{PREFIX}:Capture_RBV", on_capture)
        client.put(f"{PREFIX}:Capture", True, timeout=10.0)

        assert window_over.wait(30.0)
        watching.close()
        assert int(client.get(f"{PREFIX}:Captured", timeout=10.0)) == CAPTURED_FRAMES
        assert float(client.get(f"{PREFIX}:Exposure_RBV", timeout=10.0)) == 25.0
        assert int(client.get(f"{PREFIX}:FrameCount", timeout=10.0)) > 0
        client.put(f"{PREFIX}:Acquire", False, timeout=10.0)

    camera_service.stop()
    assert (store / "camera1" / "zarr.json").exists()


async def test_the_frame_count_follows_the_camera_and_not_the_clock(
    controller: tuple[MMCameraController, FakeCore],
) -> None:
    """A tick with no new frame publishes nothing.

    A client reads a frame after a move and waits for ``FrameCount`` to
    advance, so a count that rises on its own hands it the frame it had.
    """
    camera, core = controller

    await camera.publish_frame()
    published = camera.frame_count.get()
    assert published == 1
    assert np.array_equal(camera.buffer.get(), np.full(FRAME_SHAPE, 1, dtype=np.uint8))

    await camera.publish_frame()
    assert camera.frame_count.get() == published

    camera.grab_once()
    await camera.publish_frame()
    assert camera.frame_count.get() == published + 1
    assert np.array_equal(
        camera.buffer.get(), np.full(FRAME_SHAPE, core.snapped, dtype=np.uint8)
    )


async def test_a_bounded_window_closes_where_its_last_frame_is_written(
    controller: tuple[MMCameraController, FakeCore], tmp_path: Path
) -> None:
    """``Captured`` and ``Capture`` are answered without waiting for a tick."""
    camera, _ = controller
    store = tmp_path / "window.zarr"

    await camera.file_path.put(str(store))
    await camera.num_capture.put(2)
    await camera.capture.put(True)

    camera.grab_once()
    camera.grab_once()
    camera.grab_once()

    await camera.capture.wait_for_value(False, timeout=TIMEOUT)

    assert camera.captured.get() == 2
    assert camera.capture.get() is False
    assert (store / DATA_KEY / "zarr.json").exists()


async def test_a_second_window_counts_from_zero(
    controller: tuple[MMCameraController, FakeCore], tmp_path: Path
) -> None:
    """Naming a store starts ``Captured`` over, so a client can wait on it."""
    camera, _ = controller
    await camera.file_path.put(str(tmp_path / "first.zarr"))
    await camera.num_capture.put(2)
    await camera.capture.put(True)
    camera.grab_once()
    camera.grab_once()
    await camera.capture.wait_for_value(False, timeout=TIMEOUT)
    assert camera.captured.get() == 2

    await camera.file_path.put(str(tmp_path / "second.zarr"))

    assert camera.captured.get() == 0
    await camera.capture.put(True)
    camera.grab_once()
    camera.grab_once()
    await camera.capture.wait_for_value(False, timeout=TIMEOUT)
    assert camera.captured.get() == 2
    assert (tmp_path / "second.zarr" / DATA_KEY / "zarr.json").exists()


async def test_closing_an_unbounded_window_publishes_what_it_wrote(
    controller: tuple[MMCameraController, FakeCore], tmp_path: Path
) -> None:
    """``Captured`` is final once ``Capture`` falls, with no tick in between."""
    camera, _ = controller
    await camera.file_path.put(str(tmp_path / "window.zarr"))
    await camera.num_capture.put(0)
    await camera.capture.put(True)
    for _ in range(3):
        camera.grab_once()

    await camera.capture.put(False)

    assert camera.captured.get() == 3


def test_uncropping_grows_the_readout_back_to_the_whole_sensor() -> None:
    """One clear leaves the size the offsets allowed, which is short of the sensor."""
    core = FakeCore()
    core.setROI(2, 1, 3, 2)

    whole = Roi(0, 0, FRAME_SHAPE[1], FRAME_SHAPE[0])
    assert uncrop(core) == whole  # type: ignore[arg-type]
    assert core.roi == tuple(whole)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        pytest.param("1,1,2,2", "0,0,6,4", id="back-to-the-whole-sensor"),
        pytest.param("2,1,2,2", "1,0,5,4", id="wider-from-a-smaller-offset"),
    ],
)
async def test_a_roi_widens_again_from_a_cropped_camera(
    controller: tuple[MMCameraController, FakeCore], first: str, second: str
) -> None:
    """A camera capping the width at the room left beyond its offset takes both.

    The second ROI is wider than what is left of the sensor beyond the first
    one's offset, which such a camera refuses while it stands cropped. A
    ``DahengGalaxy`` camera refuses it and the ``DemoCamera`` adapter does
    not, so `FakeCore` is what the cap is reproduced on.
    """
    camera, core = controller

    await camera.roi.put(first)
    await camera.roi.put(second)

    assert core.roi == tuple(Roi.parse(second))
    assert camera.roi.get() == second


async def test_a_roi_write_waits_for_the_frame_the_camera_is_taking(
    controller: tuple[MMCameraController, FakeCore],
) -> None:
    """A camera driven by two threads at once can take the process down.

    A write rebuilds the driver's buffers, so it waits for the exposure in
    flight rather than running beside it.
    """
    camera, core = controller
    core.sequences = False
    core.may_expose.clear()
    await camera.acquire.put(True)
    assert core.exposing.wait(TIMEOUT)

    writing = asyncio.ensure_future(camera.roi.put("1,1,2,2"))
    landed, _ = await asyncio.wait({writing}, timeout=0.5)
    assert not landed, "the write reached the camera during an exposure"

    core.may_expose.set()
    await writing
    await camera.acquire.put(False)

    assert core.overlapped == []
    assert core.roi == (1, 1, 2, 2)


@pytest.mark.parametrize("setting", ["roi", "property"])
async def test_a_setting_refused_mid_sequence_pauses_it(
    controller: tuple[MMCameraController, FakeCore], setting: str
) -> None:
    """Micro-Manager refuses some writes during a sequence; the sequence resumes."""
    camera, core = controller
    await camera.acquire.put(True)
    await until(lambda: core.sequencing, camera)

    if setting == "roi":
        await camera.roi.put("1,1,2,2")
        assert core.roi == (1, 1, 2, 2)
        assert camera.roi.get() == "1,1,2,2"
    else:
        gain = camera.sub_controllers["properties"].attributes["Gain"]
        await gain.put("3")
        assert core.properties["Gain"] == "3"
        assert gain.get() == "3"

    assert core.sequencing
    await camera.acquire.put(False)


async def test_a_fault_is_forgotten_once_grabbing_restarts(
    controller: tuple[MMCameraController, FakeCore],
) -> None:
    """Toggling ``Acquire`` after a fault puts the camera back to work."""
    camera, core = controller
    core.fault = RuntimeError("camera unplugged")
    await camera.acquire.put(True)
    assert await asyncio.to_thread(camera.wait_until_idle, TIMEOUT)
    await camera.publish_frame()
    assert camera.state.get() == "faulted"
    core.fault = None

    await camera.acquire.put(False)
    await camera.acquire.put(True)
    await camera.publish_frame()

    assert camera.state.get() == "acquiring"
    await camera.acquire.put(False)


async def test_a_setting_is_applied_off_the_event_loop(
    controller: tuple[MMCameraController, FakeCore],
) -> None:
    """Micro-Manager blocks, so a put reaches it from a worker thread."""
    camera, core = controller

    await camera.exposure.put(25.0)

    assert camera.exposure.get() == 25.0
    assert core.threads
    assert threading.current_thread().name not in core.threads


async def test_the_sensor_size_is_reported_as_width_and_height(
    controller: tuple[MMCameraController, FakeCore],
) -> None:
    camera, _ = controller

    assert camera.sensor_size.get().tolist() == [FRAME_SHAPE[1], FRAME_SHAPE[0]]


async def test_frames_come_from_the_sequence_and_not_from_exposing_each_one(
    controller: tuple[MMCameraController, FakeCore],
) -> None:
    """A camera that takes a sequence is read through its circular buffer."""
    camera, core = controller
    snapped = core.snapped

    await camera.acquire.put(True)
    core.produce(2)

    await until(lambda: camera.frame_count.get() == 3, camera)

    assert core.sequencing
    assert core.popped == 2
    assert core.snapped == snapped
    assert camera.state.get() == "acquiring"

    await camera.acquire.put(False)
    await camera.publish_frame()
    assert camera.state.get() == "idle"
    assert core.sequencing is False


async def test_no_property_is_read_from_the_camera_while_it_sequences(
    controller: tuple[MMCameraController, FakeCore],
) -> None:
    """Polling a property mid-sequence would end it on some adapters.

    The DahengGalaxy adapter delivers no further frame once ``PixelType`` is
    read during a sequence, so every property poll waits for the camera to be
    idle. Nothing but a write changes a property meanwhile, and a write
    updates the attribute itself.
    """
    camera, core = controller
    await camera.acquire.put(True)
    await until(lambda: core.sequencing, camera)

    await camera._core_io.update(camera.pixel_dtype)
    properties = camera.sub_controllers["properties"].attributes
    for attribute in properties.values():
        await camera._property_io.update(attribute)
    await properties["Gain"].put("3")

    assert core.read_mid_sequence == []
    assert properties["Gain"].get() == "3"

    # the same polls do reach an idle camera
    await camera.acquire.put(False)
    await until(lambda: not core.sequencing, camera)
    await camera._core_io.update(camera.pixel_dtype)
    assert camera.pixel_dtype.get().name == "uint8"


def test_the_board_reset_runs_on_a_port_with_no_board(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The DTR/RTS toggling and the wait for the board's answer, without the delays."""
    monkeypatch.setattr(uc2_controller, "RESET_HOLD", 0.0)
    monkeypatch.setattr(uc2_controller, "RESET_SETTLE", 0.0)

    serial = uc2_controller.open_board("loop://", 115200, 0.01)
    try:
        assert serial.is_open
        assert serial.rts is False
    finally:
        serial.close()


async def test_a_property_poll_reads_under_the_camera_lock(
    controller: tuple[MMCameraController, FakeCore],
) -> None:
    """A sequence starting between the check and the read would take the read.

    On the Daheng that read ends the sequence for good, so the check and the
    read are one step under the lock ``_start_sequence`` runs under.
    """
    camera, core = controller
    core.guarded = camera._camera_lock.locked

    for attribute in camera.sub_controllers["properties"].attributes.values():
        await camera._property_io.update(attribute)
    await camera._core_io.update(camera.pixel_dtype)

    assert core.read_unguarded == []


async def test_an_adapter_that_refuses_a_sequence_is_exposed_per_frame() -> None:
    """The camera still gives frames when it takes no sequence."""
    core = FakeCore(sequences=False)
    camera = MMCameraController(core, LABEL, DATA_KEY)  # type: ignore[arg-type]
    await camera.initialise()
    camera.post_initialise()

    await camera.acquire.put(True)
    try:
        await until(lambda: core.snapped > 1, camera)
    finally:
        await camera.disconnect()

    assert core.popped == 0
    assert camera.frame_count.get() > 1


async def test_a_camera_that_fails_says_so_and_can_be_restarted(
    controller: tuple[MMCameraController, FakeCore],
) -> None:
    """Grabbing stops on a fault, and ``reconnect`` puts it back to work."""
    camera, core = controller
    core.fault = RuntimeError("camera unplugged")

    await camera.acquire.put(True)
    assert await asyncio.to_thread(camera.wait_until_idle, TIMEOUT)
    await camera.publish_frame()

    assert camera.state.get() == "faulted"
    assert camera.last_error.get() == "RuntimeError: camera unplugged"

    core.fault = None
    core.popped_a_frame.clear()
    await camera.reconnect()
    core.produce(1)

    assert await asyncio.to_thread(core.popped_a_frame.wait, TIMEOUT)
    await camera.publish_frame()

    assert core.popped == 1
    assert camera.state.get() == "acquiring"
    assert camera.last_error.get() == "RuntimeError: camera unplugged"


@pytest.fixture
async def board() -> AsyncGenerator[tuple[UC2Controller, FakeBoard], None]:
    """Return a UC2 controller on a board that answers, brought up as ``FastCS`` does."""
    serial = FakeBoard()
    controller = UC2Controller(serial)
    await controller.initialise()
    controller.post_initialise()
    yield controller, serial
    await controller.disconnect()


@pytest.mark.parametrize(
    ("steps", "position"),
    [
        pytest.param(
            {1: 46, 2: 156, 3: 0}, {"x": 14.72, "y": 49.92, "z": 0.0}, id="um"
        ),
        pytest.param(
            {1: -46, 2: 0, 3: 25},
            {"x": -14.72, "y": 0.0, "z": 8.0},
            id="negative",
        ),
    ],
)
async def test_an_axis_starts_from_where_the_board_left_its_stepper(
    steps: dict[int, int], position: dict[str, float]
) -> None:
    """The board keeps its steppers across a restart, so each axis asks it once.

    The board answers in steps, framed in ``++`` and ``--``; an axis reads
    micrometres. A negative position has a minus sign the framing must not
    take with it.
    """
    serial = FakeBoard(positions=steps)
    controller = UC2Controller(serial)
    await controller.initialise()
    controller.post_initialise()
    axes = controller.sub_controllers["stage"].sub_controllers["axis"]

    try:
        for axis in position:
            await axes.sub_controllers[axis].position.bind_update_callback()()
    finally:
        await controller.disconnect()

    assert {
        axis: axes.sub_controllers[axis].position.get() for axis in position
    } == pytest.approx(position)


async def test_an_axis_is_commanded_and_echoes_what_it_took(
    board: tuple[UC2Controller, FakeBoard],
) -> None:
    """The board reports nothing, so the readback is the commanded value."""
    controller, serial = board
    axis = controller.sub_controllers["stage"].sub_controllers["axis"]

    await axis.sub_controllers["y"].position.put(12.5)

    assert axis.sub_controllers["y"].position.get() == 12.5
    command = msgspec.json.decode(serial.written[-1])
    assert command["motor"]["steppers"][0]["stepperid"] == 2
    assert command["motor"]["steppers"][0]["position"] == int(12.5 * 1000 / 320)


async def test_a_laser_is_commanded_in_its_own_counts(
    board: tuple[UC2Controller, FakeBoard],
) -> None:
    """Intensity travels as the board's integer, and is read back."""
    controller, serial = board

    await controller.sub_controllers["laser1"].intensity.put(500)

    assert controller.sub_controllers["laser1"].intensity.get() == 500
    command = msgspec.json.decode(serial.written[-1])
    assert command["LASERval"] == 500
    assert command["LASERid"] == 1


async def test_the_uc2_devices_are_built_from_what_the_service_serves(
    uc2_service: Service,
) -> None:
    """The stage takes its axes from PVI, and the laser its limits."""
    stage = UC2MotorDevice(uc2_service.prefix, name="stage")
    laser = UC2LaserDevice(uc2_service.prefix, wavelength=650, name="laser")
    await stage.connect()
    await laser.connect()

    assert set(stage.axis) == {"x", "y", "z"}
    assert set(await stage.read()) == {"stage-axis-x", "stage-axis-y", "stage-axis-z"}

    described = await laser.intensity.describe()
    assert described["laser-intensity"]["limits"]["display"] == {"low": 0, "high": 1023}


async def test_the_camera_publishes_the_properties_it_lets_one_write(
    controller: tuple[MMCameraController, FakeCore],
) -> None:
    """Read-only properties are left out, and a PV name takes no spaces."""
    camera, core = controller
    properties = camera.sub_controllers["properties"]

    assert set(properties.attributes) == {"Gain", "Photon_Flux"}

    await properties.attributes["Photon_Flux"].put("7")

    assert core.properties["Photon Flux"] == "7"
    assert properties.attributes["Photon_Flux"].get() == "7"


async def test_pixel_dtype_maps_to_the_pixel_type_the_camera_supports(
    controller: tuple[MMCameraController, FakeCore],
) -> None:
    """A dtype the camera reads out in sets ``PixelType`` and retypes the buffer."""
    camera, core = controller
    choices = cast("Enum[Any]", camera.pixel_dtype.datatype).enum_cls
    assert [choice.name for choice in choices] == ["uint8", "uint16"]
    assert camera.pixel_dtype.get().name == "uint8"

    await camera.pixel_dtype.put(choices["uint16"])

    assert core.properties["PixelType"] == "16bit"
    assert camera.pixel_dtype.get().name == "uint16"
    assert camera.buffer.datatype.array_dtype == np.uint16
    assert camera.buffer.get().dtype == np.uint16
    assert "PixelType" not in camera.sub_controllers["properties"].attributes


async def test_the_pixel_dtype_is_refused_while_a_capture_writes(
    controller: tuple[MMCameraController, FakeCore], tmp_path: Path
) -> None:
    """The store's dtype is fixed when the window opens; it takes again after."""
    camera, core = controller
    choices = cast("Enum[Any]", camera.pixel_dtype.datatype).enum_cls
    await camera.file_path.put(str(tmp_path / "window.zarr"))
    await camera.num_capture.put(2)
    await camera.capture.put(True)

    with pytest.raises(RuntimeError, match="while a capture writes"):
        await camera.pixel_dtype.put(choices["uint16"])
    assert core.properties["PixelType"] == "8bit"

    camera.grab_once()
    camera.grab_once()
    await camera.capture.wait_for_value(False, timeout=TIMEOUT)
    assert camera.capture.get() is False
    await camera.pixel_dtype.put(choices["uint16"])
    assert core.properties["PixelType"] == "16bit"


async def test_the_camera_publishes_only_the_properties_chosen() -> None:
    """A chosen name the camera lacks, or cannot write, is skipped."""
    core = FakeCore()
    camera = MMCameraController(core, LABEL, DATA_KEY, ["Gain", "CameraName", "Nope"])  # type: ignore[arg-type]
    await camera.initialise()
    camera.post_initialise()
    try:
        assert set(camera.sub_controllers["properties"].attributes) == {"Gain"}
    finally:
        await camera.disconnect()


async def test_a_fault_mid_capture_ends_the_window(
    controller: tuple[MMCameraController, FakeCore], tmp_path: Path
) -> None:
    """A client waits for ``Capture`` to fall, and no frame will end it now."""
    camera, core = controller
    await camera.file_path.put(str(tmp_path / "interrupted.zarr"))
    await camera.num_capture.put(10)
    await camera.capture.put(True)

    core.fault = RuntimeError("camera unplugged")
    await camera.acquire.put(True)
    assert await asyncio.to_thread(camera.wait_until_idle, TIMEOUT)
    await camera.capture.wait_for_value(False, timeout=TIMEOUT)

    await camera.publish_frame()

    assert camera.capture.get() is False
    assert camera.state.get() == "faulted"
