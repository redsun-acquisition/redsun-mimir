from __future__ import annotations

import logging

from psygnal.qt import start_emitting_from_queue
from qtpy import QtWidgets
from redsun.containers.qt_container import QtAppContainer
from redsun.containers.components import component

from redsun_mimir.device.youseetoo import MimirLaserModel, MimirSerialModel
from redsun_mimir.presenter import LightController
from redsun_mimir.view import LightWidget


class _LightUC2App(QtAppContainer):
    serial: MimirSerialModel = component(
        layer="device",
        alias="Serial",
        port="COM3",
    )
    laser: MimirLaserModel = component(
        layer="device",
        alias="Laser 1",
        wavelength=650,
        egu="mW",
        intensity_range=(0, 1023),
        step_size=1,
        id=1,
    )
    ctrl: LightController = component(layer="presenter", timeout=5.0)
    widget: LightWidget = component(layer="view")


def light_widget_uc2() -> None:
    """Run a local UC2 example.

    Launches a Qt ``LightWidget`` app
    with a UC2 device configuration.
    """
    logger = logging.getLogger("redsun")
    logger.setLevel(logging.DEBUG)
    app = QtWidgets.QApplication([])

    container = _LightUC2App(session="redsun-mimir")
    container.build()
    container.run()

    start_emitting_from_queue()
    app.exec()
