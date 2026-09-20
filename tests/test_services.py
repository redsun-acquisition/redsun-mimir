"""The camera service: its controller, and the process a session launches."""

from __future__ import annotations

import asyncio
import threading
import time
from typing import TYPE_CHECKING, Any

import numpy as np
import pytest

from redsun_mimir.services.mmcore_camera import MMCameraController

from .conftest import CAMERA_PREFIX, needs_mm_adapters

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Sequence
    from pathlib import Path

    from numpy.typing import NDArray
    from redsun.services import Service

PREFIX = CAMERA_PREFIX.rstrip(":")
CAPTURED_FRAMES = 4
DATA_KEY = "cam"
FRAME_SHAPE = (4, 4)


class FakeCore:
    """A camera whose frames the test takes one at a time.

    Every frame carries the number of the call that produced it, so a test can
    tell one from the next.
    """

    def __init__(self) -> None:
        self.snapped = 0
        self.exposure = 100.0
        self.roi: tuple[int, ...] = (0, 0, *FRAME_SHAPE)
        self.threads: list[str] = []

    def snap(self) -> NDArray[Any]:
        self.snapped += 1
        return np.full(FRAME_SHAPE, self.snapped, dtype=np.uint8)

    def getExposure(self) -> float:
        self.threads.append(threading.current_thread().name)
        return self.exposure

    def setExposure(self, exposure: float) -> None:
        self.threads.append(threading.current_thread().name)
        self.exposure = exposure

    def getROI(self) -> Sequence[int]:
        return self.roi

    def setROI(self, *roi: int) -> None:
        self.roi = tuple(roi)


@pytest.fixture
async def controller() -> AsyncGenerator[tuple[MMCameraController, FakeCore], None]:
    """Return a controller on a fake camera, brought up as ``FastCS`` does."""
    core = FakeCore()
    controller = MMCameraController(core, DATA_KEY)  # type: ignore[arg-type]
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


async def test_a_setting_is_applied_off_the_event_loop(
    controller: tuple[MMCameraController, FakeCore],
) -> None:
    """Micro-Manager blocks, so a put reaches it from a worker thread."""
    camera, core = controller

    await camera.exposure.put(25.0)

    assert camera.exposure.get() == 25.0
    assert core.threads
    assert threading.current_thread().name not in core.threads
