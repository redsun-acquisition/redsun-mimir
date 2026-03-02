"""Shared fixtures for redsun-mimir tests."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

import pytest
from pymmcore_plus import CMMCorePlus as Core
from qtpy.QtWidgets import QApplication
from redsun.virtual import VirtualContainer

from redsun_mimir.device._mocks import MockLightDevice
from redsun_mimir.device.mmcore import MMCoreStageDevice

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator

    from qtpy.QtCore import QCoreApplication


@pytest.fixture(scope="session")
def qapp() -> Generator[QCoreApplication, None, None]:
    """Session-scoped QApplication instance."""
    if sys.platform == "linux" and not os.environ.get("DISPLAY"):
        pytest.skip("requires a display (Qt) on Linux")
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def virtual_container() -> VirtualContainer:
    """Fresh VirtualContainer for each test."""
    return VirtualContainer()


@pytest.fixture(scope="function")
def xy_mock_motor(name: str = "xystage") -> Iterator[MMCoreStageDevice]:
    """Single-axis mock motor device."""
    core = Core.instance()
    yield MMCoreStageDevice(
        name,
        config="demoxy",
    )
    core.unloadDevice(name)


@pytest.fixture
def mock_led() -> MockLightDevice:
    """Binary mock LED device."""
    return MockLightDevice(
        "led",
        wavelength=450,
        binary=True,
        intensity_range=(0, 0),
    )


@pytest.fixture
def mock_laser() -> MockLightDevice:
    """Continuous mock laser device."""
    return MockLightDevice(
        "laser",
        wavelength=650,
        egu="mW",
        intensity_range=(0, 100),
        step_size=1,
    )
