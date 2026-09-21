"""The services: their controllers, and the processes a session launches."""

from __future__ import annotations

import asyncio
import threading
import time
from queue import Queue
from typing import TYPE_CHECKING, Any

import msgspec
import numpy as np
import pytest
from redsun.services import Service

from redsun_mimir.device.youseetoo import UC2LaserDevice, UC2MotorDevice
from redsun_mimir.services.mmcore_camera import MMCameraController
from redsun_mimir.services.uc2_controller import UC2Controller

from .conftest import CAMERA_PREFIX, needs_mm_adapters

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Sequence
    from pathlib import Path

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
    report, and a laser command with an acknowledgement alone.
    """

    def __init__(self) -> None:
        self.written: list[bytes] = []
        self.is_open = True
        self._answers: list[bytes] = []

    def reset_input_buffer(self) -> None:
        pass

    def write(self, packet: bytes) -> int:
        self.written.append(packet)
        request = msgspec.json.decode(packet)
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
        self.properties = {"Gain": "0", "Photon Flux": "1", "CameraName": "fake"}
        self.sequences = sequences
        self.sequencing = False
        self.fault: Exception | None = None
        self.popped_a_frame = threading.Event()
        self._buffer: Queue[NDArray[Any]] = Queue()

    def produce(self, frames: int = 1) -> None:
        """Put *frames* into the circular buffer, as the camera would."""
        for _ in range(frames):
            self._buffer.put(np.full(FRAME_SHAPE, self.popped + 1, dtype=np.uint8))

    def snap(self) -> NDArray[Any]:
        if self.sequencing:
            raise RuntimeError("cannot expose while a sequence acquisition runs")
        self.snapped += 1
        return np.full(FRAME_SHAPE, self.snapped, dtype=np.uint8)

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

    def setROI(self, *roi: int) -> None:
        if self.sequencing:
            raise RuntimeError("Cannot set ROI while a sequence runs")
        self.roi = tuple(roi)

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
        client.put(f"{PREFIX}:Capture", True, timeout=10.0)

        captured = 0
        deadline = time.monotonic() + 30
        while captured < CAPTURED_FRAMES and time.monotonic() < deadline:
            captured = int(client.get(f"{PREFIX}:Captured", timeout=10.0))
            time.sleep(0.1)

        assert captured == CAPTURED_FRAMES
        assert not bool(client.get(f"{PREFIX}:Capture_RBV", timeout=10.0))
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

    await asyncio.sleep(0.05)

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
    await asyncio.sleep(0.05)
    assert camera.captured.get() == 2

    await camera.file_path.put(str(tmp_path / "second.zarr"))

    assert camera.captured.get() == 0
    await camera.capture.put(True)
    camera.grab_once()
    camera.grab_once()
    await asyncio.sleep(0.05)
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
        await camera.sub_controllers["properties"].attributes["Gain"].put("3")
        assert core.properties["Gain"] == "3"

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
    await asyncio.sleep(0.05)

    await camera.publish_frame()

    assert camera.capture.get() is False
    assert camera.state.get() == "faulted"
