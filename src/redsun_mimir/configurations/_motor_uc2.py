from __future__ import annotations

import logging
from pathlib import Path

from redsun.containers import component
from redsun.qt import QtAppContainer

_CONFIG = Path(__file__).parent / "motor_configuration.yaml"


def run_youseetoo_motor_container() -> None:
    """Run a UC2 motor example.

    Launches a Qt ``MotorView`` app with UC2 serial and motor devices.
    """
    from redsun_mimir.device.youseetoo import MimirMotorDevice, MimirSerialDevice
    from redsun_mimir.presenter import MotorPresenter
    from redsun_mimir.view import MotorView

    logging.getLogger("redsun").setLevel(logging.DEBUG)

    class MotorUC2App(QtAppContainer, config=_CONFIG):
        serial = component(MimirSerialDevice, layer="device", from_config="serial")
        motor = component(MimirMotorDevice, layer="device", from_config="motor")
        ctrl = component(MotorPresenter, layer="presenter", from_config="ctrl")
        widget = component(MotorView, layer="view", from_config="widget")

    MotorUC2App().run()
