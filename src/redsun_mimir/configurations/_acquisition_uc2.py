from __future__ import annotations

import logging
from pathlib import Path

from redsun.containers import component
from redsun.qt import QtAppContainer

_CONFIG = Path(__file__).parent / "uc2_acquisition_configuration.yaml"


def run_youseetoo_acquisition_container() -> None:
    """Run a UC2 acquisition + detector example.

    Launches a Qt ``AcquisitionView`` app with a background
    ``DetectorPresenter`` and ``MedianPresenter`` using UC2 devices.
    """
    from redsun_mimir.device import MockMotorDevice
    from redsun_mimir.device.mmcore import MMCoreCameraDevice
    from redsun_mimir.presenter import (
        AcquisitionPresenter,
        DetectorPresenter,
        MedianPresenter,
    )
    from redsun_mimir.view import AcquisitionView, DetectorView, ImageView

    logging.getLogger("redsun").setLevel(logging.DEBUG)

    class AcquisitionDetectorUC2App(QtAppContainer, config=_CONFIG):
        camera = component(MMCoreCameraDevice, layer="device", from_config="camera")
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
        acq_widget = component(AcquisitionView, layer="view", from_config="acq_widget")
        img_widget = component(ImageView, layer="view", from_config="img_widget")
        det_widget = component(DetectorView, layer="view", from_config="det_widget")

    AcquisitionDetectorUC2App().run()
