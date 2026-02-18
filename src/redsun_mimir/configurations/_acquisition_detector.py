from __future__ import annotations

import logging
from pathlib import Path

from redsun.containers import component
from redsun.qt import QtAppContainer

_CONFIG = Path(__file__).parent / "acquisition_detector_configuration.yaml"


def acquisition_detector_widget() -> None:
    """Run a local mock example.

    Launches a Qt ``AcquisitionView`` app with a background
    ``DetectorPresenter`` and ``MedianPresenter``.
    """
    from redsun_mimir.device import MockMotorDevice
    from redsun_mimir.device.microscope import SimulatedCameraDevice
    from redsun_mimir.device.mmcore import MMCoreCameraDevice
    from redsun_mimir.presenter import (
        AcquisitionPresenter,
        DetectorPresenter,
        MedianPresenter,
    )
    from redsun_mimir.view import AcquisitionView, DetectorView

    logging.getLogger("redsun").setLevel(logging.DEBUG)

    class AcquisitionDetectorApp(QtAppContainer, config=_CONFIG):
        camera1 = component(MMCoreCameraDevice, layer="device", from_config="camera1")
        camera2 = component(
            SimulatedCameraDevice, layer="device", from_config="camera2"
        )
        motor = component(MockMotorDevice, layer="device", from_config="motor")
        median_ctrl = component(
            MedianPresenter, layer="presenter", from_config="median_ctrl"
        )
        det_ctrl = component(
            DetectorPresenter, layer="presenter", from_config="det_ctrl"
        )
        acq_ctrl = component(
            AcquisitionPresenter, layer="presenter", from_config="acq_ctrl"
        )
        acq_widget = component(
            AcquisitionView, layer="view", from_config="acq_widget"
        )
        det_widget = component(DetectorView, layer="view", from_config="det_widget")

    AcquisitionDetectorApp().run()
