from __future__ import annotations

import logging
from pathlib import Path

from redsun.containers import component
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

_CONFIG = Path(__file__).parent / "acquisition_detector_configuration.yaml"


class _AcquisitionDetectorApp(QtAppContainer, config=_CONFIG):
    camera1: MMCoreCameraDevice = component(layer="device", from_config="camera1")
    camera2: SimulatedCameraDevice = component(layer="device", from_config="camera2")
    motor: MockMotorDevice = component(layer="device", from_config="motor")
    median_ctrl: MedianPresenter = component(
        layer="presenter", from_config="median_ctrl"
    )
    det_ctrl: DetectorController = component(layer="presenter", from_config="det_ctrl")
    acq_ctrl: AcquisitionController = component(
        layer="presenter", from_config="acq_ctrl"
    )
    acq_widget: AcquisitionWidget = component(layer="view", from_config="acq_widget")
    det_widget: DetectorWidget = component(layer="view", from_config="det_widget")


def acquisition_detector_widget() -> None:
    """Run a local mock example.

    Launches a Qt ``AcquisitionWidget`` app with a background
    ``DetectorController`` and ``MedianPresenter``.
    """
    logging.getLogger("redsun").setLevel(logging.DEBUG)
    _AcquisitionDetectorApp().run()
