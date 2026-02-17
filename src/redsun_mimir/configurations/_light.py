from __future__ import annotations

import logging

from redsun.containers.components import component
from redsun.containers.qt_container import QtAppContainer

from redsun_mimir.device import MockLightDevice
from redsun_mimir.presenter import LightController
from redsun_mimir.view import LightWidget


class _LightApp(QtAppContainer):
    led: MockLightDevice = component(
        layer="device",
        alias="Mock LED",
        wavelength=300,
        binary=True,
        intensity_range=(0, 0),
    )
    laser: MockLightDevice = component(
        layer="device",
        alias="Mock laser",
        wavelength=650,
        egu="mW",
        intensity_range=(0, 100),
        step_size=1,
    )
    ctrl: LightController = component(layer="presenter", timeout=5.0)
    widget: LightWidget = component(layer="view")


def light_widget() -> None:
    """Run a local mock example.

    Launches a Qt ``LightWidget`` app
    with mock device configurations.
    """
    logging.getLogger("redsun").setLevel(logging.DEBUG)
    _LightApp(session="redsun-mimir").run()
