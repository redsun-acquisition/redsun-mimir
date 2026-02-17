from __future__ import annotations

import logging

from psygnal.qt import start_emitting_from_queue
from qtpy import QtCore, QtWidgets
from redsun.containers.qt_container import QtAppContainer
from redsun.containers.components import component

from redsun_mimir.device import MockMotorDevice
from redsun_mimir.device.mmcore import MMCoreCameraDevice
from redsun_mimir.presenter import (
    AcquisitionController,
    DetectorController,
    MedianPresenter,
)
from redsun_mimir.view import AcquisitionWidget, DetectorWidget


class _AcquisitionDetectorUC2App(QtAppContainer):
    camera: MMCoreCameraDevice = component(
        layer="device",
        alias="Mock1",
        sensor_shape=(100, 100),
    )
    motor: MockMotorDevice = component(
        layer="device",
        alias="Mock motor",
        axis=["X", "Y", "Z"],
        step_sizes={"X": 100.0, "Y": 100.0, "Z": 100.0},
        egu="um",
    )
    median_ctrl: MedianPresenter = component(layer="presenter")
    det_ctrl: DetectorController = component(layer="presenter", timeout=5.0)
    acq_ctrl: AcquisitionController = component(
        layer="presenter",
        timeout=5.0,
        callbacks=["DetectorController", "MedianPresenter"],
    )
    acq_widget: AcquisitionWidget = component(layer="view")
    det_widget: DetectorWidget = component(layer="view")


def acquisition_detector_widget_uc2() -> None:
    """Run a local UC2 example.

    Launches a Qt ``AcquisitionWidget`` app with a background
    ``DetectorController`` and ``MedianPresenter``.
    """
    logger = logging.getLogger("redsun")
    logger.setLevel(logging.DEBUG)

    app = QtWidgets.QApplication([])

    container = _AcquisitionDetectorUC2App(session="redsun-mimir")
    container.build()

    acq_widget = container.views["acq_widget"]
    det_widget = container.views["det_widget"]

    window = QtWidgets.QMainWindow()
    window.setCentralWidget(acq_widget)
    det_widget_dock = QtWidgets.QDockWidget("Detector Control")
    det_widget_dock.setWidget(det_widget)
    window.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, det_widget_dock)
    window.setWindowTitle("Acquisition widget")
    window.adjustSize()
    window.show()

    start_emitting_from_queue()
    app.exec()
