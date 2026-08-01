"""Shared fixtures for redsun-mimir tests."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

import pytest
from ophyd_async.core import DeviceMap, StandardReadable, soft_signal_rw
from pymmcore_plus import CMMCorePlus as Core
from pymmcore_plus import find_micromanager
from qtpy.QtWidgets import QApplication
from redsun.aio import get_shared_loop
from redsun.storage import BaseStorage, SessionPathProvider, clear_registry
from redsun.storage.backends._memory import MemoryIO
from redsun.virtual import VirtualContainer

from redsun_mimir.device._mocks import MockLightDevice
from redsun_mimir.device.mmcore import MMDemoCamera

if TYPE_CHECKING:
    import asyncio
    from collections.abc import AsyncGenerator, Generator
    from pathlib import Path

    from ophyd_async.core import SignalRW
    from qtpy.QtCore import QCoreApplication


#: Micro-Manager device adapters are downloaded, not pip-installed, and their
#: device interface version must match the installed ``pymmcore``. Tests that
#: load a real device are skipped when none are discoverable.
needs_mm_adapters = pytest.mark.skipif(
    find_micromanager() is None,
    reason="no Micro-Manager device adapters; run 'mmcore install --test-adapters'",
)


class FakeXYStage(StandardReadable):
    """Minimal ``MotorProtocol``-conformant test double for an XY stage.

    Presenter/view/acquisition-layer tests only need *some* device that
    structurally satisfies
    [`MotorProtocol`][redsun_mimir.protocols.MotorProtocol] (an
    ``AsyncReadable`` exposing ``axis: DeviceMap[SignalRW[float]]``) whose
    axes show up in ``read()``/``describe()``. Using this instead of
    ``MMDemoXYStage`` keeps those tests off the process-wide
    ``CMMCorePlus`` singleton, which only tolerates one device per name.

    It is built exactly like the production stages: axis signals go straight
    into the ``DeviceMap`` and are never bound as top-level attributes first
    (a ``Device`` cannot be re-parented), and they are registered with
    [`add_readables`][ophyd_async.core.StandardReadable.add_readables] so
    readings are keyed ``<device>-axis-<name>``.
    """

    axis: DeviceMap[SignalRW[float]]

    def __init__(self, name: str, /, axes: tuple[str, ...] = ("x", "y")) -> None:
        signals = {axis: soft_signal_rw(float, initial_value=0.0) for axis in axes}
        self.axis = DeviceMap(signals)
        self.add_readables(list(self.axis.values()))
        super().__init__(name)


@pytest.fixture(scope="session", autouse=True)
def qapp() -> Generator[QCoreApplication, None, None]:
    """Session-scoped QApplication instance."""
    if (
        sys.platform == "linux"
        and os.environ.get("QT_QPA_PLATFORM") != "offscreen"
        and not os.environ.get("DISPLAY")
    ):
        pytest.skip("requires a display (Qt) on Linux")
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture(scope="session", autouse=True)
def shared_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Ensure the shared event loop is running in its background daemon thread."""
    loop = get_shared_loop()
    yield loop


@pytest.fixture(autouse=True)
def _reset_mmcore() -> Generator[None, None, None]:
    """Unload every Micro-Manager device after each test.

    MM devices are loaded by name into a process-wide ``CMMCorePlus``
    singleton (and only one camera device may be active at a time); leaving
    them loaded would collide with the next test reusing the same name or
    claiming the single camera slot.
    """
    yield
    Core.instance().reset()


@pytest.fixture(autouse=True)
def _clear_storage_registry() -> Generator[None, None, None]:
    """Clear redsun's process-wide storage registry after each test."""
    yield
    clear_registry()


@pytest.fixture
def virtual_container() -> VirtualContainer:
    """Fresh VirtualContainer for each test."""
    return VirtualContainer()


@pytest.fixture
async def motor_stage() -> FakeXYStage:
    """Return a connected two-axis ``FakeXYStage`` double (see class docstring)."""
    device = FakeXYStage("xystage")
    await device.connect(mock=True)
    return device


@pytest.fixture
async def mm_camera(tmp_path: Path) -> AsyncGenerator[MMDemoCamera, None]:
    """Return a connected ``MMDemoCamera`` (demo adapter) backed by an in-memory store."""
    storage = BaseStorage(
        io=MemoryIO(),
        path_provider=SessionPathProvider(base_dir=tmp_path, session="test"),
    )
    device = MMDemoCamera("camera1", storage=storage)
    await device.connect(mock=False)
    yield device


@pytest.fixture
async def mock_led() -> MockLightDevice:
    """Mock LED device with a narrow intensity range."""
    device = MockLightDevice("led", wavelength=450, range=(0.0, 1.0))
    await device.connect(mock=True)
    return device


@pytest.fixture
async def mock_laser() -> MockLightDevice:
    """Mock laser device with a wide intensity range."""
    device = MockLightDevice("laser", wavelength=650, range=(0.0, 100.0))
    await device.connect(mock=True)
    return device


@pytest.fixture
async def mock_binary_led() -> MockLightDevice:
    """Mock LED device that is on/off only."""
    device = MockLightDevice("binary_led", wavelength=300, binary=True)
    await device.connect(mock=True)
    return device
