from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

from redsun import AsDevice, Declare

from redsun_mimir.device import MockLightDevice
from redsun_mimir.device.mmcore import MMCamera, MMStage

from ._base import MimirApp


class MimirSimulator(MimirApp):
    """The simulation session: demo camera and stages, mock light sources."""

    config = Path(__file__).parent / "full_configuration.yaml"

    mmcamera: Annotated[AsDevice[MMCamera], Declare(service="camera1_ioc")]
    XY: Annotated[AsDevice[MMStage], Declare(service="xy_stage")]
    Z: Annotated[AsDevice[MMStage], Declare(service="z_stage")]
    laser: AsDevice[MockLightDevice]
    led: AsDevice[MockLightDevice]


def build_simulation_container() -> MimirSimulator:
    """Return the simulation session, unbuilt, so it can be inspected."""
    return MimirSimulator(log_level=logging.DEBUG)


def run_simulation_container() -> None:
    """Run the full simulation example with mock devices."""
    build_simulation_container().run()
