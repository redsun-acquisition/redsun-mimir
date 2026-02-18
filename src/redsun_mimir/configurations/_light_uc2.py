from __future__ import annotations

import logging
from pathlib import Path

from redsun.containers import component
from redsun.qt import QtAppContainer

_CONFIG = Path(__file__).parent / "uc2_light_configuration.yaml"


def run_youseetoo_light_container() -> None:
    """Run a UC2 light example.

    Launches a Qt ``LightView`` app with UC2 serial and laser devices.
    """
    from redsun_mimir.device.youseetoo import MimirLaserDevice, MimirSerialDevice
    from redsun_mimir.presenter import LightPresenter
    from redsun_mimir.view import LightView

    logging.getLogger("redsun").setLevel(logging.DEBUG)

    class LightUC2App(QtAppContainer, config=_CONFIG):
        serial = component(MimirSerialDevice, layer="device", from_config="serial")
        laser = component(MimirLaserDevice, layer="device", from_config="laser")
        ctrl = component(LightPresenter, layer="presenter", from_config="ctrl")
        widget = component(LightView, layer="view", from_config="widget")

    LightUC2App().run()
