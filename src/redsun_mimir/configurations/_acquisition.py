from __future__ import annotations

import logging
from pathlib import Path

from redsun.containers import device, presenter, view
from redsun.qt import QtAppContainer

_CONFIG = Path(__file__).parent / "acquisition_configuration.yaml"


def run_acquisition_container() -> None:
    """Run a local mock example.

    Launches a Qt ``AcquisitionView`` app with a background
    ``DetectorPresenter`` and ``MedianPresenter``.
    """
    from redsun_mimir.device.mmcore import MMCoreCameraDevice, MMCoreStageDevice
    from redsun_mimir.presenter.acquisition import AcquisitionPresenter
    from redsun_mimir.presenter.detector import DetectorPresenter
    from redsun_mimir.presenter.median import MedianPresenter
    from redsun_mimir.presenter.storage import FileStoragePresenter
    from redsun_mimir.view.acquisition import AcquisitionView
    from redsun_mimir.view.detector import DetectorView
    from redsun_mimir.view.image import ImageView
    from redsun_mimir.view.storage import FileStorageView

    logging.getLogger("redsun").setLevel(logging.DEBUG)

    class AcquisitionDetectorApp(QtAppContainer, config=_CONFIG):
        mm_camera = device(MMCoreCameraDevice, from_config="camera1")
        xy_motor = device(MMCoreStageDevice, from_config="xy-motor")
        z_motor = device(MMCoreStageDevice, from_config="z-motor")
        storage_ctrl = presenter(FileStoragePresenter, from_config="storage_ctrl")
        median_ctrl = presenter(MedianPresenter, from_config="median_ctrl")
        det_ctrl = presenter(DetectorPresenter, from_config="det_ctrl")
        acq_ctrl = presenter(AcquisitionPresenter, from_config="acq_ctrl")
        acq_widget = view(AcquisitionView, from_config="acq_widget")
        img_widget = view(ImageView, from_config="img_widget")
        det_widget = view(DetectorView, from_config="det_widget")
        storage_widget = view(FileStorageView, from_config="storage_widget")

    AcquisitionDetectorApp().run()
