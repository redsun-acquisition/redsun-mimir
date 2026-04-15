from __future__ import annotations

import logging
from pathlib import Path

from redsun.containers import declare_device, declare_presenter, declare_view
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
        mm_camera = declare_device(MMCoreCameraDevice, from_config="camera1")
        xy_motor = declare_device(MMCoreStageDevice, from_config="xy-motor")
        z_motor = declare_device(MMCoreStageDevice, from_config="z-motor")
        storage_ctrl = declare_presenter(
            FileStoragePresenter, from_config="storage_ctrl"
        )
        median_ctrl = declare_presenter(MedianPresenter, from_config="median_ctrl")
        det_ctrl = declare_presenter(DetectorPresenter, from_config="det_ctrl")
        acq_ctrl = declare_presenter(AcquisitionPresenter, from_config="acq_ctrl")
        acq_widget = declare_view(AcquisitionView, from_config="acq_widget")
        img_widget = declare_view(ImageView, from_config="img_widget")
        det_widget = declare_view(DetectorView, from_config="det_widget")
        storage_widget = declare_view(FileStorageView, from_config="storage_widget")

    AcquisitionDetectorApp().run()
