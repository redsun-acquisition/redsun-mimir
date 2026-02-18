from __future__ import annotations

import logging
from pathlib import Path

from redsun.containers import component
from redsun.qt import QtAppContainer

_CONFIG = Path(__file__).parent / "uc2_acquisition_detector_configuration.yaml"


def acquisition_detector_widget_uc2() -> None:
    """Run a UC2 acquisition + detector example.

    Launches a Qt ``AcquisitionWidget`` app with a background
    ``DetectorController`` and ``MedianPresenter`` using UC2 devices.
    """
    from redsun_mimir.device import MockMotorDevice
    from redsun_mimir.device.mmcore import MMCoreCameraDevice
    from redsun_mimir.presenter import (
        AcquisitionController,
        DetectorController,
        MedianPresenter,
    )
    from redsun_mimir.view import AcquisitionWidget, DetectorWidget

    logging.getLogger("redsun").setLevel(logging.DEBUG)

    class _AcquisitionDetectorUC2App(QtAppContainer, config=_CONFIG):
        camera = component(MMCoreCameraDevice, layer="device", from_config="camera")
        motor = component(MockMotorDevice, layer="device", from_config="motor")
        median_ctrl = component(
            MedianPresenter, layer="presenter", from_config="median_ctrl"
        )
        det_ctrl = component(
            DetectorController, layer="presenter", from_config="det_ctrl"
        )
        acq_ctrl = component(
            AcquisitionController, layer="presenter", from_config="acq_ctrl"
        )
        acq_widget = component(
            AcquisitionWidget, layer="view", from_config="acq_widget"
        )
        det_widget = component(DetectorWidget, layer="view", from_config="det_widget")

    _AcquisitionDetectorUC2App().run()
