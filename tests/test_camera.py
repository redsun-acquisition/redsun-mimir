"""Fly-scan lifecycle test for MMDemoCamera (demo adapter).

Mirrors ``test_plan_with_device_and_callback_writers`` in redsun's own SDK
test suite (``tests/sdk/storage/test_integration_plans.py``), adapted to
drive the real MMCore camera device and its custom arm/trigger/data logics
instead of a synthetic ``StandardDetector``.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

import bluesky.plan_stubs as bps
import bluesky.preprocessors as bpp
import pytest
from bluesky.run_engine import RunEngine as BlueskyRunEngine
from ophyd_async.core import TriggerInfo
from ophyd_async.testing import assert_emitted
from pymmcore_plus import CMMCorePlus
from redsun.aio import run_coro
from redsun.storage import BaseStorage, SessionPathProvider
from redsun.storage.backends._memory import MemoryIO

from redsun_mimir.device.mmcore import MMDemoCamera

if TYPE_CHECKING:
    from collections.abc import Generator

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def bluesky_re() -> Generator[BlueskyRunEngine, None, None]:
    """Return a standard bluesky RunEngine on its own event loop."""
    loop = asyncio.new_event_loop()
    loop.set_debug(True)
    yield BlueskyRunEngine({}, call_returns_result=True, loop=loop)


@pytest.fixture
def demo_camera(
    tmp_path: Path, bluesky_re: BlueskyRunEngine
) -> Generator[tuple[MMDemoCamera, BaseStorage, MemoryIO], None, None]:
    """Yield a connected MMDemoCamera (demo adapter) backed by ``MemoryIO``.

    Connects the device on the RunEngine's event loop so that all
    ophyd-async signal infrastructure (including the frame-counter setter
    used from the streaming thread) is bound to the same loop that drives
    the plan.
    """
    io = MemoryIO()
    provider = SessionPathProvider(base_dir=tmp_path, session="camera")
    storage = BaseStorage(io=io, path_provider=provider)

    cam = MMDemoCamera("cam", storage=storage)
    asyncio.run_coroutine_threadsafe(cam.connect(mock=False), bluesky_re.loop).result(
        timeout=10.0
    )
    yield cam, storage, io

    CMMCorePlus.instance().reset()


# ---------------------------------------------------------------------------
# Fly-scan lifecycle test
# ---------------------------------------------------------------------------


def test_fly_scan_lifecycle(
    demo_camera: tuple[MMDemoCamera, BaseStorage, MemoryIO],
    bluesky_re: BlueskyRunEngine,
) -> None:
    """Fly scan plan lifecycle with MMDemoCamera (demo adapter).

    Verifies that the standard bluesky fly-scan protocol
    (stage -> prepare -> declare_stream -> kickoff -> collect_while_completing -> unstage)
    produces the expected stream document sequence and writes the correct
    number of frames through ``BaseStorage``/``MemoryIO`` using the MMCore
    background streaming thread.
    """
    cam, storage, io = demo_camera
    RE = bluesky_re
    n_frames = 4

    docs: dict[str, list[Any]] = defaultdict(list)
    RE.subscribe(lambda name, doc: docs[name].append(doc))

    @bpp.stage_decorator([cam])  # type: ignore[untyped-decorator]
    @bpp.run_decorator()  # type: ignore[untyped-decorator]
    def fly_plan() -> Any:
        yield from bps.prepare(cam, TriggerInfo(number_of_events=n_frames), wait=True)
        yield from bps.declare_stream(cam, name="primary", collect=True)
        yield from bps.kickoff(cam, wait=True)
        yield from bps.collect_while_completing(
            flyers=[cam], dets=[cam], flush_period=0.1
        )

    RE(fly_plan())

    # deterministic settle: close() awaits any drain still flushing
    run_coro(storage.close())

    # At least one stream_datum batch must have been emitted
    assert len(docs["stream_datum"]) >= 1
    assert_emitted(
        docs,
        start=1,
        descriptor=1,
        stream_resource=1,
        stream_datum=len(docs["stream_datum"]),
        stop=1,
    )
    # All n_frames must be accounted for across all batches
    total = sum(
        sd["indices"]["stop"] - sd["indices"]["start"] for sd in docs["stream_datum"]
    )
    assert total == n_frames
    assert len(io.stores) == 1
    assert len(io.stores[0].arrays["cam"]) == n_frames
