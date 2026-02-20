from __future__ import annotations

import logging
from pathlib import Path

from redsun.containers import device, presenter, view
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
        camera = device(MMCoreCameraDevice, from_config="camera")
        motor = device(MockMotorDevice, from_config="motor")
        median_ctrl = presenter(
            MedianPresenter, from_config="median_ctrl"
        )
        det_ctrl = presenter(
            DetectorPresenter, from_config="det_ctrl"
        )
        acq_ctrl = presenter(
            AcquisitionPresenter, from_config="acq_ctrl"
        )
        acq_widget = view(AcquisitionView, from_config="acq_widget")
        img_widget = view(ImageView, from_config="img_widget")
        det_widget = view(DetectorView, from_config="det_widget")

    AcquisitionDetectorUC2App().run()
