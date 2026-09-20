"""The camera service, launched the way a session launches it."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest
from redsun.services import Service
from redsun.services._transports import PV_ACCESS

from redsun_mimir.services.mmcore_camera import READY

from .conftest import needs_mm_adapters

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

PREFIX = "MIMIR-TESTCAM"
CAPTURED_FRAMES = 4


@pytest.fixture
def camera_service(monkeypatch: pytest.MonkeyPatch) -> Iterator[Service]:
    """Launch the camera service on the demo adapter, and stop it after."""
    monkeypatch.setenv("EPICS_PVA_ADDR_LIST", "")
    service = Service(
        "camera1",
        prefix=f"{PREFIX}:",
        module="redsun_mimir.services.mmcore_camera",
        args=["--adapter", "DemoCamera", "--device", "DCam"],
        ready=READY,
        transport=PV_ACCESS,
        stop_timeout=10,
    )
    service.start()
    yield service
    service.stop()


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
        client.put(f"{PREFIX}:FileUri", str(store), timeout=10.0)
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
