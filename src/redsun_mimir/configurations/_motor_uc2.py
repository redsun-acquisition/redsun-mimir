from __future__ import annotations

import logging
from pathlib import Path

from redsun.containers import AppContainer, component

from redsun_mimir.device.youseetoo import MimirMotorModel, MimirSerialModel
from redsun_mimir.presenter import MotorController
from redsun_mimir.view import MotorWidget

_CONFIG = Path(__file__).parent / "uc2_motor_configuration.yaml"


class _MotorUC2App(AppContainer, config=_CONFIG):
    serial: MimirSerialModel = component(layer="device", from_config="serial")
    stage: MimirMotorModel = component(layer="device", from_config="stage")
    ctrl: MotorController = component(layer="presenter", from_config="ctrl")
    widget: MotorWidget = component(layer="view", from_config="widget")


def stage_widget_uc2() -> None:
    """Run a local UC2 example.

    Launches a Qt ``MotorWidget`` app
    with a UC2 device configuration.
    """
    logging.getLogger("redsun").setLevel(logging.DEBUG)
    _MotorUC2App().run()
