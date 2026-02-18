from __future__ import annotations

import logging
from pathlib import Path

from redsun.containers import AppContainer, component

from redsun_mimir.device.youseetoo import MimirLaserDevice, MimirSerialDevice
from redsun_mimir.presenter import LightController
from redsun_mimir.view import LightWidget

_CONFIG = Path(__file__).parent / "uc2_light_configuration.yaml"


class _LightUC2App(AppContainer, config=_CONFIG):
    serial: MimirSerialDevice = component(layer="device", from_config="serial")
    laser: MimirLaserDevice = component(layer="device", from_config="laser")
    ctrl: LightController = component(layer="presenter", from_config="ctrl")
    widget: LightWidget = component(layer="view", from_config="widget")


def light_widget_uc2() -> None:
    """Run a local UC2 example.

    Launches a Qt ``LightWidget`` app
    with a UC2 device configuration.
    """
    logging.getLogger("redsun").setLevel(logging.DEBUG)
    _LightUC2App().run()
