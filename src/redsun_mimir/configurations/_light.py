from __future__ import annotations

import logging
from pathlib import Path

from redsun.containers import AppContainer, component

from redsun_mimir.device import MockLightDevice
from redsun_mimir.presenter import LightController
from redsun_mimir.view import LightWidget

_CONFIG = Path(__file__).parent / "mock_light_configuration.yaml"


class _LightApp(AppContainer, config=_CONFIG):
    led = component(MockLightDevice, layer="device", from_config="led")
    laser = component(MockLightDevice, layer="device", from_config="laser")
    ctrl = component(LightController, layer="presenter", from_config="ctrl")
    widget = component(LightWidget, layer="view", from_config="widget")


def light_widget() -> None:
    """Run a local mock example.

    Launches a Qt ``LightWidget`` app
    with mock device configurations.
    """
    logging.getLogger("redsun").setLevel(logging.DEBUG)
    _LightApp().run()
