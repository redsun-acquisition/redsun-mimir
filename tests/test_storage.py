"""Tests for how MMCore camera devices wire into redsun's storage split.

``redsun_mimir.storage`` and ``FileStoragePresenter`` no longer exist -
``SessionPathProvider`` moved to redsun and is tested there
(``tests/sdk/storage``). What is left for this bundle to own is
``MMBaseCameraDevice`` deciding which ``BaseStorage`` it writes through and
publishing it via ``register_storage``/``get_storage``, per
``docs/explanation/decisions/0002-storage-dual-context-redesign.md``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from redsun.storage import BaseStorage, SessionPathProvider, get_storage
from redsun.storage.backends._acquire_zarr import AcquireZarrIO
from redsun.storage.backends._memory import MemoryIO

from redsun_mimir.device.mmcore import MMDemoCamera


async def test_explicit_storage_is_used_and_registered(tmp_path: Path) -> None:
    """Passing ``storage=`` wires the camera to that instance and publishes it."""
    storage = BaseStorage(
        io=MemoryIO(),
        path_provider=SessionPathProvider(base_dir=tmp_path, session="s"),
    )
    cam = MMDemoCamera("cam", storage=storage)
    await cam.connect(mock=False)

    assert cam.storage is storage
    assert get_storage("cam", storage.mimetype) is storage


async def test_default_storage_uses_acquire_zarr(tmp_path: Path) -> None:
    """Without an explicit ``storage=``, the camera builds its own AcquireZarrIO-backed store."""
    cam = MMDemoCamera("cam2")
    await cam.connect(mock=False)

    assert cam.storage.mimetype == AcquireZarrIO.mimetype
    assert get_storage("cam2", AcquireZarrIO.mimetype) is cam.storage


async def test_two_cameras_get_independent_default_storages(tmp_path: Path) -> None:
    """Two cameras without an explicit storage each get their own instance."""
    cam_a = MMDemoCamera("cam_a")
    await cam_a.connect(mock=False)
    core = cam_a.core
    core.setCameraDevice("")  # release the single-camera slot for cam_b

    cam_b = MMDemoCamera("cam_b")
    await cam_b.connect(mock=False)

    assert cam_a.storage is not cam_b.storage
    assert get_storage("cam_a", cam_a.storage.mimetype) is cam_a.storage
    assert get_storage("cam_b", cam_b.storage.mimetype) is cam_b.storage


async def test_register_storage_rejects_duplicate_group(tmp_path: Path) -> None:
    """A second camera reusing a name already registered under the same mimetype raises."""
    storage = BaseStorage(
        io=MemoryIO(),
        path_provider=SessionPathProvider(base_dir=tmp_path, session="s"),
    )
    cam = MMDemoCamera("dup", storage=storage)
    # release the name and the single-camera slot so the second construction
    # gets past MM's own guards and reaches register_storage()
    cam.core.setCameraDevice("")
    cam.core.unloadDevice("dup")
    with pytest.raises(KeyError, match="already registered"):
        MMDemoCamera("dup", storage=storage)
