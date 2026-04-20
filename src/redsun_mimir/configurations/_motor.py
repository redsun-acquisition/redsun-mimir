from __future__ import annotations

import logging

from redsun.containers import declare_device, declare_presenter, declare_view
from redsun.qt import QtAppContainer


def run_stage_container() -> None:
    """Run a local mock motor example.

    Launches a Qt ``MotorView`` app with a mock motor device.
    """
    from redsun_mimir.device.mmcore import MMDemoXYStage, MMDemoZStage
    from redsun_mimir.presenter.motor import MotorPresenter
    from redsun_mimir.view.motor import MotorView

    logging.getLogger("redsun").setLevel(logging.DEBUG)

    class MotorApp(QtAppContainer):
        xy_motor = declare_device(MMDemoXYStage, config="demoxy")
        z_motor = declare_device(MMDemoZStage, config="demoz")
        ctrl = declare_presenter(MotorPresenter)
        widget = declare_view(MotorView)

    MotorApp().run()
