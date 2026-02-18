from __future__ import annotations

import logging
from pathlib import Path

from redsun.containers import component
from redsun.qt import QtAppContainer

_CONFIG = Path(__file__).parent / "mock_light_configuration.yaml"


def light_widget() -> None:
    """Run a local mock light example.

    Launches a Qt ``LightWidget`` app with a mock light device.
    """
    from redsun_mimir.device import MockLightDevice
    from redsun_mimir.presenter import LightController
    from redsun_mimir.view import LightWidget

    logging.getLogger("redsun").setLevel(logging.DEBUG)

    class LightApp(QtAppContainer, config=_CONFIG):
        light = component(MockLightDevice, layer="device", from_config="light")
        ctrl = component(LightController, layer="presenter", from_config="ctrl")
        widget = component(LightWidget, layer="view", from_config="widget")

    LightApp().run()
