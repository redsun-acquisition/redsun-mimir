from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

from redsun import AsDevice, Declare

from redsun_mimir.device.mmcore import MMCamera
from redsun_mimir.device.youseetoo import UC2LaserDevice, UC2MotorDevice

from ._base import MimirApp


class MimirMicroscope(MimirApp):
    """The UC2 microscope session: a Micro-Manager camera and a UC2 board."""

    config = Path(__file__).parent / "uc2_full_configuration.yaml"

    iscat: Annotated[AsDevice[MMCamera], Declare(service="camera_ioc")]
    stage: Annotated[AsDevice[UC2MotorDevice], Declare(service="uc2_board")]
    laser: Annotated[AsDevice[UC2LaserDevice], Declare(service="uc2_board")]


def build_uc2_container() -> MimirMicroscope:
    """Return the UC2 session, unbuilt, so it can be inspected."""
    return MimirMicroscope(log_level=logging.DEBUG)


def run_uc2_container() -> None:
    """Run the UC2 microscope example with its shipped configuration."""
    build_uc2_container().run()
