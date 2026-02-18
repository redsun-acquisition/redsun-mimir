from __future__ import annotations

import logging
from pathlib import Path

from redsun.containers import component
from redsun.containers.qt_container import QtAppContainer

from redsun_mimir.device import MockLightDevice
from redsun_mimir.presenter import LightController
from redsun_mimir.view import LightWidget

_CONFIG = Path(__file__).parent / "mock_light_configuration.yaml"


class _LightApp(QtAppContainer, config=_CONFIG):
    led: MockLightDevice = component(layer="device", from_config="led")
    laser: MockLightDevice = component(layer="device", from_config="laser")
    ctrl: LightController = component(layer="presenter", from_config="ctrl")
    widget: LightWidget = component(layer="view", from_config="widget")


def light_widget() -> None:
    """Run a local mock example.

    Launches a Qt ``LightWidget`` app
    with mock device configurations.
    """
    logging.getLogger("redsun").setLevel(logging.DEBUG)
    _LightApp().run()
