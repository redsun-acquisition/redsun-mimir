from __future__ import annotations

import logging

from psygnal.qt import start_emitting_from_queue
from qtpy import QtWidgets
from redsun.containers.qt_container import QtAppContainer
from redsun.containers.components import component

from redsun_mimir.device.youseetoo import MimirMotorModel, MimirSerialModel
from redsun_mimir.presenter import MotorController
from redsun_mimir.view import MotorWidget


class _MotorUC2App(QtAppContainer):
    serial: MimirSerialModel = component(
        layer="device",
        alias="Serial",
        port="COM3",
    )
    stage: MimirMotorModel = component(
        layer="device",
        alias="Stage",
        axis=["X", "Y", "Z"],
        step_sizes={"X": 100.0, "Y": 100.0, "Z": 100.0},
        egu="um",
    )
    ctrl: MotorController = component(layer="presenter", timeout=5.0)
    widget: MotorWidget = component(layer="view")


def stage_widget_uc2() -> None:
    """Run a local UC2 example.

    Launches a Qt ``MotorWidget`` app
    with a UC2 device configuration.
    """
    logger = logging.getLogger("redsun")
    logger.setLevel(logging.DEBUG)
    app = QtWidgets.QApplication([])

    container = _MotorUC2App(session="redsun-mimir")
    container.build()
    container.run()

    start_emitting_from_queue()
    app.exec()
