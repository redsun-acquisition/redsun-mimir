"""Fly-scan lifecycle for a camera served by its own process.

The camera writes nothing here: the service does, and the device reports what
it wrote. The plan is the standard fly sequence, so what this pins is the
document stream and the store that comes out of it.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse
from urllib.request import url2pathname

import bluesky.plan_stubs as bps
import bluesky.preprocessors as bpp
import numpy as np
import pytest
from bluesky.run_engine import RunEngine as BlueskyRunEngine
from ophyd_async.core import TriggerInfo
from ophyd_async.testing import assert_emitted
from redsun.path_provider import SessionPathProvider

from redsun_mimir.device.mmcore import MMCamera
from redsun_mimir.device.mmcore._camera import frame_shape_and_dtype

from .conftest import needs_mm_adapters

if TYPE_CHECKING:
    from collections.abc import Generator

    from redsun.services import Service

FRAMES = 4


@pytest.fixture
def bluesky_re() -> Generator[BlueskyRunEngine, None, None]:
    """Return a standard bluesky RunEngine on its own event loop."""
    loop = asyncio.new_event_loop()
    loop.set_debug(True)
    yield BlueskyRunEngine({}, call_returns_result=True, loop=loop)


@pytest.fixture
def fly_camera(
    camera_service: Service, tmp_path: Path, bluesky_re: BlueskyRunEngine
) -> MMCamera:
    """Return a camera connected on the RunEngine's loop, as a plan needs it."""
    camera = MMCamera(
        camera_service.prefix,
        path_provider=SessionPathProvider(base_dir=tmp_path, session="camera"),
        name="cam",
    )
    asyncio.run_coroutine_threadsafe(camera.connect(), bluesky_re.loop).result(
        timeout=30.0
    )
    return camera


@needs_mm_adapters
def test_fly_scan_lifecycle(
    fly_camera: MMCamera, bluesky_re: BlueskyRunEngine, tmp_path: Path
) -> None:
    """Stage, prepare, kickoff, collect, unstage, and the store that results.

    Each document batch reports frames the service has already written, so the
    frames the stream datums account for are the frames on disk. The plan runs
    twice: the second window counts its own frames, not the first's as well.
    """
    docs: dict[str, list[Any]] = defaultdict(list)
    bluesky_re.subscribe(lambda name, doc: docs[name].append(doc))

    @bpp.stage_decorator([fly_camera])  # type: ignore[untyped-decorator]
    @bpp.run_decorator()  # type: ignore[untyped-decorator]
    def fly_plan() -> Any:
        yield from bps.prepare(
            fly_camera, TriggerInfo(number_of_events=FRAMES), wait=True
        )
        yield from bps.declare_stream(fly_camera, name="primary", collect=True)
        yield from bps.kickoff(fly_camera, wait=True)
        yield from bps.collect_while_completing(
            flyers=[fly_camera], dets=[fly_camera], flush_period=0.1
        )

    bluesky_re(fly_plan())
    bluesky_re(fly_plan())

    assert_emitted(
        docs,
        start=2,
        descriptor=2,
        stream_resource=2,
        stream_datum=len(docs["stream_datum"]),
        stop=2,
    )
    written = sum(
        datum["indices"]["stop"] - datum["indices"]["start"]
        for datum in docs["stream_datum"]
    )
    assert written == 2 * FRAMES

    store = Path(url2pathname(urlparse(docs["stream_resource"][0]["uri"]).path))
    assert (store / "cam" / "zarr.json").exists()


@needs_mm_adapters
async def test_a_roi_is_written_as_text_and_sizes_the_frames(
    mm_camera: MMCamera,
) -> None:
    """The one form of the setting a client can put over PVAccess."""
    await mm_camera.roi.set("10,20,100,50")

    assert await mm_camera.roi.get_value() == "10,20,100,50"
    assert (await frame_shape_and_dtype(mm_camera))[0] == (50, 100)

    await mm_camera.roi.set("0,0,512,512")


@needs_mm_adapters
async def test_the_camera_carries_its_properties_into_its_configuration(
    mm_camera: MMCamera,
) -> None:
    """A property the camera lets one write is a setting like any other.

    The view builds its panel from ``describe_configuration``, so a property
    that stays inside the service is a property nobody can change.
    """
    described = await mm_camera.describe_configuration()

    assert f"{mm_camera.name}-exposure" in described
    assert f"{mm_camera.name}-sensor_size" in described
    assert f"{mm_camera.name}-properties-Binning" in described

    await mm_camera.properties["Binning"].set("2")

    assert await mm_camera.properties["Binning"].get_value() == "2"
    readings = await mm_camera.read_configuration()
    assert readings[f"{mm_camera.name}-properties-Binning"]["value"] == "2"


@needs_mm_adapters
async def test_a_pixel_type_change_reaches_the_frames_and_the_dtype(
    mm_camera: MMCamera,
) -> None:
    """The buffer carries the new dtype and ``pixel_dtype`` says which."""
    assert (await mm_camera.buffer.get_value()).dtype == np.uint8

    await mm_camera.properties["PixelType"].set("16bit")

    deadline = time.monotonic() + 10.0
    while (await mm_camera.buffer.get_value()).dtype != np.uint16:
        assert time.monotonic() < deadline, "no 16-bit frame arrived"
        await asyncio.sleep(0.05)
    assert await mm_camera.pixel_dtype.get_value() == "uint16"
    assert (await frame_shape_and_dtype(mm_camera))[1] == "uint16"
