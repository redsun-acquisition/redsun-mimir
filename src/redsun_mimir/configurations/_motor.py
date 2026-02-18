from __future__ import annotations

import logging
from pathlib import Path

from redsun.containers import component
from redsun.qt import QtAppContainer

_CONFIG = Path(__file__).parent / "mock_motor_configuration.yaml"


def stage_widget() -> None:
    """Run a local mock motor example.

    Launches a Qt ``MotorWidget`` app with a mock motor device.
    """
    from redsun_mimir.device import MockMotorDevice
    from redsun_mimir.presenter import MotorController
    from redsun_mimir.view import MotorWidget

    logging.getLogger("redsun").setLevel(logging.DEBUG)

    class MotorApp(QtAppContainer, config=_CONFIG):
        motor = component(MockMotorDevice, layer="device", from_config="motor")
        ctrl = component(MotorController, layer="presenter", from_config="ctrl")
        widget = component(MotorWidget, layer="view", from_config="widget")

    MotorApp().run()
