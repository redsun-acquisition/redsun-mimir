from __future__ import annotations

import logging
from pathlib import Path

from redsun.containers import component
from redsun.qt import QtAppContainer

from redsun_mimir.device.youseetoo import MimirMotorDevice, MimirSerialDevice
from redsun_mimir.presenter import MotorController
from redsun_mimir.view import MotorWidget

_CONFIG = Path(__file__).parent / "uc2_motor_configuration.yaml"


def stage_widget_uc2() -> None:
    """Run a UC2 motor example.

    Launches a Qt ``MotorWidget`` app with UC2 serial and motor devices.
    """
    logging.getLogger("redsun").setLevel(logging.DEBUG)

    class _MotorUC2App(QtAppContainer, config=_CONFIG):
        serial = component(MimirSerialDevice, layer="device", from_config="serial")
        stage = component(MimirMotorDevice, layer="device", from_config="stage")
        ctrl = component(MotorController, layer="presenter", from_config="ctrl")
        widget = component(MotorWidget, layer="view", from_config="widget")

    _MotorUC2App().run()
