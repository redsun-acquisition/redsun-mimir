from __future__ import annotations

import logging
from pathlib import Path

from redsun.containers import AppContainer, component

from redsun_mimir.device.youseetoo import MimirLaserDevice, MimirSerialDevice
from redsun_mimir.presenter import LightController
from redsun_mimir.view import LightWidget

_CONFIG = Path(__file__).parent / "uc2_light_configuration.yaml"


class _LightUC2App(AppContainer, config=_CONFIG):
    serial = component(MimirSerialDevice, layer="device", from_config="serial")
    laser = component(MimirLaserDevice, layer="device", from_config="laser")
    ctrl = component(LightController, layer="presenter", from_config="ctrl")
    widget = component(LightWidget, layer="view", from_config="widget")


def light_widget_uc2() -> None:
    """Run a local UC2 example.

    Launches a Qt ``LightWidget`` app
    with a UC2 device configuration.
    """
    logging.getLogger("redsun").setLevel(logging.DEBUG)
    _LightUC2App().run()
