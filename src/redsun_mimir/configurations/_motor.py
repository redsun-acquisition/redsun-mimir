from __future__ import annotations

import logging

from psygnal.qt import start_emitting_from_queue
from qtpy import QtWidgets
from redsun.containers.qt_container import QtAppContainer
from redsun.containers.components import component

from redsun_mimir.device import MockMotorDevice
from redsun_mimir.presenter import MotorController
from redsun_mimir.view import MotorWidget


class _MotorApp(QtAppContainer):
    motor: MockMotorDevice = component(
        layer="device",
        alias="Mock motor",
        axis=["X", "Y", "Z"],
        step_sizes={"X": 100.0, "Y": 100.0, "Z": 100.0},
        egu="um",
    )
    ctrl: MotorController = component(layer="presenter", timeout=5.0)
    widget: MotorWidget = component(layer="view")


def stage_widget() -> None:
    """Run a local mock example.

    Launches a Qt ``MotorWidget`` app
    with a mock device configuration.
    """
    logger = logging.getLogger("redsun")
    logger.setLevel(logging.DEBUG)
    app = QtWidgets.QApplication([])

    container = _MotorApp(session="redsun-mimir")
    container.build()
    container.run()

    start_emitting_from_queue()
    app.exec()
