"""Shared fixtures for redsun-mimir tests."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest
from qtpy.QtWidgets import QApplication
from sunflare.virtual import VirtualBus

from redsun_mimir.device._mocks import MockLightDevice, MockMotorDevice

if TYPE_CHECKING:
    from collections.abc import Generator

    from qtpy.QtCore import QCoreApplication


@pytest.fixture(scope="session")
def qapp() -> Generator[QCoreApplication, None, None]:
    """Session-scoped QApplication instance."""
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def virtual_bus() -> VirtualBus:
    """Fresh VirtualBus for each test."""
    return VirtualBus()


@pytest.fixture
def mock_motor(name: str = "stage") -> MockMotorDevice:
    """Single-axis mock motor device."""
    return MockMotorDevice(
        name,
        axis=["X", "Y", "Z"],
        step_sizes={"X": 1.0, "Y": 1.0, "Z": 1.0},
        egu="um",
    )


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
