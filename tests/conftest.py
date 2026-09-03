"""Shared fixtures for redsun-mimir tests."""

from __future__ import annotations

import gc
import os
import sys
from functools import cached_property
from typing import TYPE_CHECKING

import pytest
from ophyd_async.core import (
    DeviceMap,
    MovableLogic,
    StandardMovable,
    StandardReadable,
    soft_signal_r_and_setter,
    soft_signal_rw,
)
from pymmcore_plus import CMMCorePlus as Core
from pymmcore_plus import find_micromanager
from qtpy.QtCore import QEvent
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

    from qtpy.QtCore import QCoreApplication


#: Micro-Manager device adapters are downloaded, not pip-installed, and their
#: device interface version must match the installed ``pymmcore``. Tests that
#: load a real device are skipped when none are discoverable.
needs_mm_adapters = pytest.mark.skipif(
    find_micromanager() is None,
    reason="no Micro-Manager device adapters; run 'mmcore install --test-adapters'",
)

#: A napari viewer needs a real OpenGL context - ``QT_QPA_PLATFORM=offscreen``
#: cannot provide one and construction dies inside PyOpenGL. Opt in on a machine
#: with a display.
needs_opengl = pytest.mark.skipif(
    not os.environ.get("MIMIR_TEST_OPENGL"),
    reason="napari needs a real OpenGL context; set MIMIR_TEST_OPENGL=1 to run",
)


class FakeAxis(StandardReadable, StandardMovable[float]):
    """Soft-signal stand-in for one movable axis.

    Built like the production axes: a readback separate from the setpoint,
    joined by a `MovableLogic`. The setter writes the readback, so a move
    lands exactly where it was sent.
    """

    def __init__(self, name: str = "") -> None:
        with self.add_children_as_readables():
            self.readback, self._readback_set = soft_signal_r_and_setter(
                float, 0.0, units="um"
            )

        async def setter(value: float | None) -> float | None:
            if value is not None:
                self._readback_set(value)
            return value

        self.setpoint = soft_signal_rw(float, 0.0, units="um", setter=setter)
        super().__init__(name)

    @cached_property
    def movable_logic(self) -> MovableLogic[float]:
        """Setpoint and readback of this axis."""
        return MovableLogic(setpoint=self.setpoint, readback=self.readback)


class FakeXYStage(StandardReadable):
    """Minimal ``MotorProtocol``-conformant test double for an XY stage.

    Presenter/view/acquisition-layer tests only need *some* device that
    structurally satisfies
    [`MotorProtocol`][redsun_mimir.protocols.MotorProtocol] whose axes show
    up in ``read()``/``describe()``. Using this instead of ``MMDemoXYStage``
    keeps those tests off the process-wide ``CMMCorePlus`` singleton, which
    only tolerates one device per name.

    It is built exactly like the production stages: axes go straight into the
    ``DeviceMap`` and are never bound as top-level attributes first (a
    ``Device`` cannot be re-parented), and they are registered with
    [`add_readables`][ophyd_async.core.StandardReadable.add_readables] so
    readings are keyed ``<device>-axis-<name>``.
    """

    axis: DeviceMap[StandardMovable[float]]

    def __init__(self, name: str, /, axes: tuple[str, ...] = ("x", "y")) -> None:
        self.axis = DeviceMap({axis: FakeAxis() for axis in axes})
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


@pytest.fixture(autouse=True)
def _destroy_widgets() -> Generator[None, None, None]:
    """Destroy the widgets a test built, between tests rather than during one.

    A view connects its own bound methods to the signals of the widgets it
    creates, so every widget a test builds sits in a reference cycle that only
    the cyclic collector can break. Left alone that collection happens at an
    arbitrary later point, and a ``QWidget`` destroyed while Qt is walking its
    widget list - which ``QApplication.setStyleSheet`` does - takes the process
    down with an access violation.
    """
    yield
    app = QApplication.instance()
    if app is None:
        return
    gc.collect()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


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
