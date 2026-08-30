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
    from redsun_mimir.device.mmcore import MMDahengCamera
    from redsun_mimir.device.youseetoo import (
        UC2LaserDevice,
        UC2MotorDevice,
        UC2Serial,
    )

    from ._base import MimirApp

    class MimirMicroscope(MimirApp, config=_CONFIG):
        serial = declare_device(UC2Serial, from_config="serial")
        iscat = declare_device(MMDahengCamera, from_config="camera")
        stage = declare_device(UC2MotorDevice, from_config="stage")
        laser = declare_device(UC2LaserDevice, from_config="laser")

    return MimirMicroscope(log_level=logging.DEBUG)


def run_uc2_container() -> None:
    """Run the full UC2 microscope with pre-shipped configuration."""
    build_uc2_container().run()
