from __future__ import annotations

import logging
from pathlib import Path

from redsun.containers import component
from redsun.qt import QtAppContainer

_CONFIG = Path(__file__).parent / "mock_acquisition_configuration.yaml"


def acquisition_widget() -> None:
    """Run a local acquisition example.

    Launches a Qt ``AcquisitionView`` app with MMCore and simulated
    camera devices.
    """
    from redsun_mimir.device.microscope import SimulatedCameraDevice
    from redsun_mimir.device.mmcore import MMCoreCameraDevice
    from redsun_mimir.presenter import AcquisitionPresenter
    from redsun_mimir.view import AcquisitionView

    logging.getLogger("redsun").setLevel(logging.DEBUG)

    class AcquisitionApp(QtAppContainer, config=_CONFIG):
        camera1 = component(MMCoreCameraDevice, layer="device", from_config="camera1")
        camera2 = component(
            SimulatedCameraDevice, layer="device", from_config="camera2"
        )
        ctrl = component(AcquisitionPresenter, layer="presenter", from_config="ctrl")
        widget = component(AcquisitionView, layer="view", from_config="widget")

    AcquisitionApp().run()
