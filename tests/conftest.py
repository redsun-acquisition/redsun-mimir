"""Shared fixtures for redsun-mimir tests."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

import numpy as np
import pytest
from ophyd_async.core import SignalR, StandardReadable, soft_signal_r_and_setter
from pymmcore_plus import CMMCorePlus as Core
from qtpy.QtWidgets import QApplication
from redsun.engine import get_shared_loop
from redsun.virtual import VirtualContainer

from redsun_mimir.device._mocks import MockLightDevice
from redsun_mimir.device.mmcore import MMCoreStageDevice

if TYPE_CHECKING:
    import asyncio
    from collections.abc import AsyncGenerator, Generator

    from qtpy.QtCore import QCoreApplication


class MockBufferDevice(StandardReadable):
    """Minimal device with a buffer signal for presenter tests."""

    buffer: SignalR[np.ndarray]

    def __init__(self, name: str, shape: tuple[int, int] = (4, 4)) -> None:
        buf, self._set_buffer = soft_signal_r_and_setter(
            np.ndarray, initial_value=np.zeros(shape, dtype=np.float64)
        )
        self.buffer = buf
        super().__init__(name=name)

    def push_frame(self, frame: np.ndarray) -> None:
        """Push a new frame — triggers all buffer subscribers synchronously."""
        self._set_buffer(frame)


def make_start(uid: str) -> dict[str, object]:
    return {"uid": uid, "time": 0.0}


def make_descriptor(uid: str, stream: str, run_uid: str) -> dict[str, object]:
    return {
        "uid": uid,
        "name": stream,
        "run_start": run_uid,
        "data_keys": {},
        "time": 0.0,
        "configuration": {},
        "hints": {},
        "object_keys": {},
    }


def make_stop(run_uid: str) -> dict[str, object]:
    return {
        "run_start": run_uid,
        "time": 0.0,
        "uid": f"stop-{run_uid}",
        "exit_status": "success",
        "reason": "",
    }


@pytest.fixture(scope="session", autouse=True)
def qapp() -> Generator[QCoreApplication, None, None]:
    """Session-scoped QApplication instance."""
    if sys.platform == "linux" and not os.environ.get("DISPLAY"):
        pytest.skip("requires a display (Qt) on Linux")
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture(scope="session", autouse=True)
def shared_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Ensure the shared event loop is running in its background daemon thread."""
    loop = get_shared_loop()
    yield loop


@pytest.fixture
def virtual_container() -> VirtualContainer:
    """Fresh VirtualContainer for each test."""
    return VirtualContainer()


@pytest.fixture
async def xy_mock_motor() -> AsyncGenerator[MMCoreStageDevice, None]:
    """XY motor device backed by the MMCore demo stage."""
    core = Core.instance()
    device = MMCoreStageDevice("xystage", config="demoxy")
    await device.connect(mock=False)
    yield device
    if "xystage" in core.getLoadedDevices():
        core.unloadDevice("xystage")


@pytest.fixture
async def mock_led() -> MockLightDevice:
    """Binary mock LED device."""
    device = MockLightDevice("led", wavelength=450, binary=True, intensity_range=(0, 0))
    await device.connect(mock=True)
    return device


@pytest.fixture
async def mock_laser() -> MockLightDevice:
    """Continuous mock laser device."""
    device = MockLightDevice(
        "laser",
        wavelength=650,
        egu="mW",
        intensity_range=(0, 100),
        step_size=1,
    )
    await device.connect(mock=True)
    return device


@pytest.fixture
async def mock_buffer_device() -> MockBufferDevice:
    """Camera-like mock device with a subscribable buffer signal."""
    device = MockBufferDevice("camera1")
    await device.connect(mock=True)
    return device
