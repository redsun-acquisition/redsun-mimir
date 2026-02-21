from __future__ import annotations

import logging
from pathlib import Path

from redsun.containers import device, presenter, view
from redsun.qt import QtAppContainer

_CONFIG = Path(__file__).parent / "motor_configuration.yaml"


def run_stage_container() -> None:
    """Run a local mock motor example.

    Launches a Qt ``MotorView`` app with a mock motor device.
    """
    from redsun_mimir.device import MockMotorDevice
    from redsun_mimir.presenter import MotorPresenter
    from redsun_mimir.view import MotorView

    logging.getLogger("redsun").setLevel(logging.DEBUG)

    class MotorApp(QtAppContainer, config=_CONFIG):
        motor = device(MockMotorDevice, from_config="motor")
        ctrl = presenter(MotorPresenter, from_config="ctrl")
        widget = view(MotorView, from_config="widget")

    MotorApp().run()
