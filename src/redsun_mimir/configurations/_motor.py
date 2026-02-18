from __future__ import annotations

import logging
from pathlib import Path

from redsun.containers import component
from redsun.containers.qt_container import QtAppContainer

from redsun_mimir.device import MockMotorDevice
from redsun_mimir.presenter import MotorController
from redsun_mimir.view import MotorWidget

_CONFIG = Path(__file__).parent / "mock_motor_configuration.yaml"


class _MotorApp(QtAppContainer, config=_CONFIG):
    motor: MockMotorDevice = component(layer="device", from_config="motor")
    ctrl: MotorController = component(layer="presenter", from_config="ctrl")
    widget: MotorWidget = component(layer="view", from_config="widget")


def stage_widget() -> None:
    """Run a local mock example.

    Launches a Qt ``MotorWidget`` app
    with a mock device configuration.
    """
    logging.getLogger("redsun").setLevel(logging.DEBUG)
    _MotorApp().run()
