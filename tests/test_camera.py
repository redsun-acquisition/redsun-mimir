"""Fly-scan lifecycle test for MMCoreCameraDevice (demo adapter).

Mirrors the ``test_fly_scan_lifecycle`` test in redsun's SDK test suite,
adapted for the MMCore camera device and its custom arm/trigger/data logics.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from itertools import count
from pathlib import Path, PurePath
from typing import Any

import bluesky.plan_stubs as bps
import bluesky.preprocessors as bpp
import numpy.typing as npt
import pytest
from bluesky.run_engine import RunEngine as BlueskyRunEngine
from ophyd_async.core import (
    StaticFilenameProvider,
    StaticPathProvider,
    TriggerInfo,
)
from ophyd_async.testing import assert_emitted
from pymmcore_plus import CMMCorePlus
from redsun.storage import DataWriter, SourceInfo

from redsun_mimir.device.mmcore import MMCoreCameraDevice

# ---------------------------------------------------------------------------
# Minimal DataWriter stub
# ---------------------------------------------------------------------------


class _ConcreteDataWriter(DataWriter):
    """Minimal in-memory DataWriter for integration tests."""

    def __init__(self) -> None:
        super().__init__()
        self._sources: dict[str, SourceInfo] = {}
        self._is_open = False
        self._written: dict[str, list[npt.NDArray[Any]]] = {}
        self._path: PurePath | None = None
        self._write_counter: count[int] = count(1)

    @property
    def is_open(self) -> bool:
        return self._is_open

    @property
    def sources(self) -> dict[str, SourceInfo]:
        return self._sources

    @property
    def file_extension(self) -> str:
        return "test"

    @property
    def mimetype(self) -> str:
        return "application/x-test"

    def set_store_path(self, path: PurePath) -> None:
        self._path = path

    def is_path_set(self) -> bool:
        return self._path is not None

    def open(self) -> None:
        self._is_open = True

    def register(self, datakey: str, info: SourceInfo) -> None:
        self._sources[datakey] = info

    def unregister(self, datakey: str) -> None:
        self._sources.pop(datakey, None)

    def write(self, datakey: str, data: npt.NDArray[Any]) -> None:
        self._written.setdefault(datakey, []).append(data)
        self._update_count(next(self._write_counter))

    def close(self) -> None:
        self._is_open = False
        self._sources.clear()
        self._write_counter = count(1)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def bluesky_re() -> BlueskyRunEngine:
    """Return a standard bluesky RunEngine on its own event loop."""
    loop = asyncio.new_event_loop()
    loop.set_debug(True)
    return BlueskyRunEngine({}, call_returns_result=True, loop=loop)


@pytest.fixture
def demo_camera(tmp_path: Path, bluesky_re: BlueskyRunEngine) -> Any:
    """Yield a connected MMCoreCameraDevice (demo adapter) with a concrete writer.

    Connects the device on the RunEngine's event loop so that all ophyd-async
    signal infrastructure (including the frame-counter setter used from the
    streaming thread) is bound to the same loop that drives the plan.
    """
    MMCoreCameraDevice.initialized = False
    writer = _ConcreteDataWriter()
    pp = StaticPathProvider(StaticFilenameProvider("cam"), PurePath(tmp_path))

    cam = MMCoreCameraDevice("cam", writer, config="demo", path_provider=pp)
    bluesky_re.loop.call_soon_threadsafe(cam.connect(mock=False))
    yield cam, writer

    # Cleanup: unload all MM devices and reset the initialized guard so other
    # tests or test re-runs don't see stale state.
    CMMCorePlus.instance().reset()
    MMCoreCameraDevice.initialized = False


# ---------------------------------------------------------------------------
# Fly-scan lifecycle test
# ---------------------------------------------------------------------------


def test_fly_scan_lifecycle(
    demo_camera: tuple[MMCoreCameraDevice, _ConcreteDataWriter],
    bluesky_re: BlueskyRunEngine,
) -> None:
    """Fly scan plan lifecycle with MMCoreCameraDevice (demo adapter).

    Verifies that the standard bluesky fly-scan protocol
    (stage → prepare → declare_stream → kickoff → collect_while_completing → unstage)
    produces the expected stream document sequence and writes the correct number
    of frames using the MMCore background streaming thread.
    """
    cam, writer = demo_camera
    RE = bluesky_re
    n_frames = 4

    docs: dict[str, list[Any]] = defaultdict(list)
    RE.subscribe(lambda name, doc: docs[name].append(doc))

    @bpp.stage_decorator([cam])
    @bpp.run_decorator()
    def fly_plan() -> Any:
        yield from bps.prepare(cam, TriggerInfo(number_of_events=n_frames), wait=True)
        yield from bps.declare_stream(cam, name="primary")
        yield from bps.kickoff(cam, wait=True)
        yield from bps.collect_while_completing(
            flyers=[cam], dets=[cam], flush_period=0.1
        )

    RE(fly_plan())

    assert_emitted(docs, start=1, descriptor=1, stream_resource=1, stop=1)
    # At least one stream_datum batch must have been emitted
    assert len(docs["stream_datum"]) >= 1
    # All n_frames must be accounted for across all batches
    total = sum(
        sd["indices"]["stop"] - sd["indices"]["start"] for sd in docs["stream_datum"]
    )
    assert total == n_frames
    assert len(writer._written.get("cam", [])) == n_frames
