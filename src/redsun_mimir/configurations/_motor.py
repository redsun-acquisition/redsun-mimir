from __future__ import annotations

import logging

from redsun.containers import declare_device, declare_presenter, declare_view
from redsun.qt import QtAppContainer

from ._wiring import wire_motor


def build_stage_container() -> QtAppContainer:
    """Return the example container, unbuilt (see `build_acquisition_container`)."""
    from redsun_mimir.device.mmcore import MMDemoXYStage, MMDemoZStage
    from redsun_mimir.presenter.motor import MotorPresenter
    from redsun_mimir.view.motor import MotorView

    logging.getLogger("redsun").setLevel(logging.DEBUG)

    class MotorApp(QtAppContainer):
        xy_motor = declare_device(MMDemoXYStage)
        z_motor = declare_device(MMDemoZStage)
        ctrl = declare_presenter(MotorPresenter)
        widget = declare_view(MotorView)

        def wire(self) -> None:
            wire_motor(self, self.ctrl, self.widget)

    return MotorApp()


def run_stage_container() -> None:
    """Run a local mock motor example.

    Launches a Qt ``MotorView`` app with a mock motor device.
    """
    build_stage_container().run()
