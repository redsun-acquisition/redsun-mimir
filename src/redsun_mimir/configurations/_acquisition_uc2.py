from __future__ import annotations

import logging

from psygnal.qt import start_emitting_from_queue
from qtpy import QtWidgets
from redsun.containers.qt_container import QtAppContainer
from redsun.containers.components import component

from redsun_mimir.device.mmcore import MMCoreCameraDevice
from redsun_mimir.presenter import AcquisitionController
from redsun_mimir.view import AcquisitionWidget


class _AcquisitionUC2App(QtAppContainer):
    camera: MMCoreCameraDevice = component(
        layer="device",
        alias="Mock1",
        sensor_shape=(100, 100),
    )
    ctrl: AcquisitionController = component(layer="presenter", timeout=5.0)
    widget: AcquisitionWidget = component(layer="view")


def acquisition_widget_uc2() -> None:
    """Run a local UC2 example.

    Launches a Qt ``AcquisitionWidget`` app
    with a UC2 device configuration.
    """
    logger = logging.getLogger("redsun")
    logger.setLevel(logging.DEBUG)

    app = QtWidgets.QApplication([])

    container = _AcquisitionUC2App(session="redsun-mimir")
    container.build()
    container.run()

    start_emitting_from_queue()
    app.exec()
