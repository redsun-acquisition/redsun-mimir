from __future__ import annotations

import logging
from pathlib import Path

from redsun.containers import declare_device, declare_presenter, declare_view
from redsun.presenter.builtins import StoragePresenter
from redsun.qt import QtAppContainer
from redsun.view.qt.builtins import StorageView

from ._wiring import wire_acquisition, wire_detector, wire_median

_CONFIG = Path(__file__).parent / "acquisition_configuration.yaml"


def build_acquisition_container() -> QtAppContainer:
    """Return the example container, unbuilt.

    Imports stay inside the factory so that importing this package does not
    pull in napari and Qt. Split out from
    [`run_acquisition_container`][redsun_mimir.configurations.run_acquisition_container]
    so tests can build the container without entering the Qt event loop.
    """
    from redsun_mimir.device.mmcore import MMDemoCamera, MMDemoXYStage, MMDemoZStage
    from redsun_mimir.presenter.acquisition import AcquisitionPresenter
    from redsun_mimir.presenter.detector import DetectorPresenter
    from redsun_mimir.presenter.median import MedianPresenter
    from redsun_mimir.view.acquisition import AcquisitionView
    from redsun_mimir.view.detector import DetectorView
    from redsun_mimir.view.image import ImageView

    logging.getLogger("redsun").setLevel(logging.DEBUG)

    class AcquisitionDetectorApp(QtAppContainer, config=_CONFIG):
        mm_camera = declare_device(MMDemoCamera, from_config="camera1")
        xy_motor = declare_device(MMDemoXYStage, from_config="xy-motor")
        z_motor = declare_device(MMDemoZStage, from_config="z-motor")
        storage_ctrl = declare_presenter(StoragePresenter, from_config="storage_ctrl")
        median_ctrl = declare_presenter(MedianPresenter, from_config="median_ctrl")
        det_ctrl = declare_presenter(DetectorPresenter, from_config="det_ctrl")
        acq_ctrl = declare_presenter(AcquisitionPresenter, from_config="acq_ctrl")
        acq_widget = declare_view(AcquisitionView, from_config="acq_widget")
        img_widget = declare_view(ImageView, from_config="img_widget")
        det_widget = declare_view(DetectorView, from_config="det_widget")
        storage_widget = declare_view(StorageView, from_config="storage_widget")

        def wire(self) -> None:
            wire_detector(self, self.det_ctrl, self.det_widget, self.img_widget)
            wire_median(self, self.median_ctrl, self.img_widget)
            wire_acquisition(
                self,
                self.acq_ctrl,
                self.acq_widget,
                storage=self.storage_ctrl,
                median=self.median_ctrl,
            )

    return AcquisitionDetectorApp()


def run_acquisition_container() -> None:
    """Run a local mock example.

    Launches a Qt ``AcquisitionView`` app with a background
    ``DetectorPresenter`` and ``MedianPresenter``.
    """
    build_acquisition_container().run()
