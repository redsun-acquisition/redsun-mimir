from __future__ import annotations

import logging

from redsun.containers.components import component
from redsun.containers.qt_container import QtAppContainer

from redsun_mimir.device import MockMotorDevice
from redsun_mimir.device.microscope import SimulatedCameraDevice
from redsun_mimir.device.mmcore import MMCoreCameraDevice
from redsun_mimir.presenter import (
    AcquisitionController,
    DetectorController,
    MedianPresenter,
)
from redsun_mimir.view import AcquisitionWidget, DetectorWidget


class _AcquisitionDetectorApp(QtAppContainer):
    camera1: MMCoreCameraDevice = component(
        layer="device",
        alias="Mock1",
        sensor_shape=(100, 100),
    )
    camera2: SimulatedCameraDevice = component(
        layer="device",
        alias="Mock2",
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


def acquisition_detector_widget() -> None:
    """Run a local mock example.

    Launches a Qt ``AcquisitionWidget`` app with a background
    ``DetectorController`` and ``MedianPresenter``.
    """
    logging.getLogger("redsun").setLevel(logging.DEBUG)
    _AcquisitionDetectorApp(session="redsun-mimir").run()
