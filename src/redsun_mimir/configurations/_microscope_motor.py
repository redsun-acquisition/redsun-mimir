from __future__ import annotations

import logging
from pathlib import Path

from redsun.containers import device, presenter, view
from redsun.qt import QtAppContainer

_CONFIG = Path(__file__).parent / "microscope_motor_configuration.yaml"


def run_microscope_motor_container() -> None:
    """Run a simulated microscope stage example.

    Launches a Qt ``MotorView`` app driven by a
    ``SimulatedStageDevice`` with XYZ axes.
    """
    from redsun_mimir.device.microscope import SimulatedStageDevice
    from redsun_mimir.presenter import MotorPresenter
    from redsun_mimir.view import MotorView

    logging.getLogger("redsun").setLevel(logging.DEBUG)

    class MicroscopeMotorApp(QtAppContainer, config=_CONFIG):
        stage = device(SimulatedStageDevice, from_config="stage")
        ctrl = presenter(MotorPresenter, from_config="ctrl")
        widget = view(MotorView, from_config="widget")

    MicroscopeMotorApp().run()
