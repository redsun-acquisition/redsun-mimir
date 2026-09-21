from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from redsun.containers import declare_device

if TYPE_CHECKING:
    from redsun.qt import QtAppContainer

_CONFIG = Path(__file__).parent / "uc2_full_configuration.yaml"


def build_uc2_container() -> QtAppContainer:
    """Return the UC2 container, unbuilt, so it can be inspected."""
    from redsun_mimir.device.mmcore import MMCamera
    from redsun_mimir.device.youseetoo import UC2LaserDevice, UC2MotorDevice

    from ._base import MimirApp

    class MimirMicroscope(MimirApp, config=_CONFIG):
        iscat = declare_device(MMCamera, service="camera_ioc")
        stage = declare_device(UC2MotorDevice, service="uc2_board")
        laser = declare_device(UC2LaserDevice, service="uc2_board", from_config="laser")

    return MimirMicroscope(log_level=logging.DEBUG)


def run_uc2_container() -> None:
    """Run the UC2 microscope example with its shipped configuration."""
    build_uc2_container().run()
