from __future__ import annotations

import logging

from psygnal.qt import start_emitting_from_queue
from qtpy import QtWidgets
from redsun.containers.qt_container import QtAppContainer
from redsun.containers.components import component

from redsun_mimir.device.mmcore import MMCoreCameraDevice
from redsun_mimir.device.microscope import SimulatedCameraDevice
from redsun_mimir.presenter import AcquisitionController
from redsun_mimir.view import AcquisitionWidget


class _AcquisitionApp(QtAppContainer):
    camera1: MMCoreCameraDevice = component(
        layer="device",
        alias="Mock1",
        sensor_shape=(100, 100),
    )
    camera2: SimulatedCameraDevice = component(
        layer="device",
        alias="Mock2",
    )
    ctrl: AcquisitionController = component(layer="presenter", timeout=5.0)
    widget: AcquisitionWidget = component(layer="view")


def acquisition_widget() -> None:
    """Run a local mock example.

    Launches a Qt ``AcquisitionWidget`` app
    with a mock device configuration.
    """
    logger = logging.getLogger("redsun")
    logger.setLevel(logging.DEBUG)

    app = QtWidgets.QApplication([])

    container = _AcquisitionApp(session="redsun-mimir")
    container.build()
    container.run()

    start_emitting_from_queue()
    app.exec()
