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
    from redsun_mimir.device.mmcore import MMCamera, MMStage

    from ._base import MimirApp

    class MimirSimulator(MimirApp, config=_CONFIG):
        mmcamera = declare_device(MMCamera, service="camera1_ioc")
        XY = declare_device(MMStage, service="xy_stage")
        Z = declare_device(MMStage, service="z_stage")
        laser = declare_device(MockLightDevice, from_config="laser")
        led = declare_device(MockLightDevice, from_config="led")

    return MimirSimulator(log_level=logging.DEBUG)


def run_simulation_container() -> None:
    """Run a local mock example.

    Launches a simulation with the full stack
    provided by mimir with mock devices.
    """
    build_simulation_container().run()
