from __future__ import annotations

import logging
from pathlib import Path

from redsun.containers import component
from redsun.qt import QtAppContainer

from redsun_mimir.device import MockLightDevice
from redsun_mimir.presenter import LightController
from redsun_mimir.view import LightWidget

_CONFIG = Path(__file__).parent / "mock_light_configuration.yaml"


def light_widget() -> None:
    """Run a local mock example.

    Launches a Qt ``LightWidget`` app
    with mock device configurations.
    """
    logging.getLogger("redsun").setLevel(logging.DEBUG)

    class _LightApp(QtAppContainer, config=_CONFIG):
        led = component(MockLightDevice, layer="device", from_config="led")
        laser = component(MockLightDevice, layer="device", from_config="laser")
        ctrl = component(LightController, layer="presenter", from_config="ctrl")
        widget = component(LightWidget, layer="view", from_config="widget")

    _LightApp().run()
