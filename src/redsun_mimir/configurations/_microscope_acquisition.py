from __future__ import annotations

import logging
from pathlib import Path

from redsun.containers import device, presenter, view
from redsun.qt import QtAppContainer

_CONFIG = Path(__file__).parent / "microscope_acquisition_configuration.yaml"


def run_microscope_acquisition_container() -> None:
    """Run a simulated microscope acquisition example.

    Launches a Qt ``AcquisitionView`` app with a
    ``SimulatedStageDevice``, a stage-aware ``SimulatedCameraDevice``,
    and a ``SimulatedLightDevice``.  The camera is wired to the stage
    via the order-independent callback registry, so the container
    declaration order does not matter.
    """
    from redsun_mimir.device.microscope import (
        SimulatedCameraDevice,
        SimulatedLightDevice,
        SimulatedStageDevice,
    )
    from redsun_mimir.presenter import (
        AcquisitionPresenter,
        DetectorPresenter,
        MedianPresenter,
    )
    from redsun_mimir.view import AcquisitionView, DetectorView, ImageView

    logging.getLogger("redsun").setLevel(logging.DEBUG)

    class MicroscopeAcquisitionApp(QtAppContainer, config=_CONFIG):
        stage = device(SimulatedStageDevice, from_config="stage")
        camera = device(SimulatedCameraDevice, from_config="camera")
        laser = device(SimulatedLightDevice, from_config="laser")
        median_ctrl = presenter(MedianPresenter, from_config="median_ctrl")
        det_ctrl = presenter(DetectorPresenter, from_config="det_ctrl")
        acq_ctrl = presenter(AcquisitionPresenter, from_config="acq_ctrl")
        acq_widget = view(AcquisitionView, from_config="acq_widget")
        img_widget = view(ImageView, from_config="img_widget")
        det_widget = view(DetectorView, from_config="det_widget")

    MicroscopeAcquisitionApp().run()
