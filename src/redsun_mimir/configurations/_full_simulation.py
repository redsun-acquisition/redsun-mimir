from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from redsun.containers import declare_device

if TYPE_CHECKING:
    from redsun.qt import QtAppContainer

_CONFIG = Path(__file__).parent / "full_configuration.yaml"


def build_simulation_container() -> QtAppContainer:
    """Return the simulation container, unbuilt, so it can be inspected."""
    from redsun_mimir.device import MockLightDevice
    from redsun_mimir.device.mmcore import MMDemoCamera, MMDemoXYStage, MMDemoZStage

    from ._base import MimirApp

    class MimirSimulator(MimirApp, config=_CONFIG):
        mmcamera = declare_device(MMDemoCamera, from_config="camera1")
        XY = declare_device(MMDemoXYStage, from_config="xy-motor")
        Z = declare_device(MMDemoZStage, from_config="z-motor")
        laser = declare_device(MockLightDevice, from_config="laser")
        led = declare_device(MockLightDevice, from_config="led")

    return MimirSimulator(log_level=logging.DEBUG)


def run_simulation_container() -> None:
    """Run a local mock example.

    Launches a simulation with the full stack
    provided by mimir with mock devices.
    """
    build_simulation_container().run()
