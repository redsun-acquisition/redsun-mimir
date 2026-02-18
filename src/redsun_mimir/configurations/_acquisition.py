from __future__ import annotations

import logging
from pathlib import Path

from redsun.containers import component
from redsun.qt import QtAppContainer

from redsun_mimir.device.microscope import SimulatedCameraDevice
from redsun_mimir.device.mmcore import MMCoreCameraDevice
from redsun_mimir.presenter import AcquisitionController
from redsun_mimir.view import AcquisitionWidget

_CONFIG = Path(__file__).parent / "mock_acquisition_configuration.yaml"


def acquisition_widget() -> None:
    """Run a local acquisition example.

    Launches a Qt ``AcquisitionWidget`` app with MMCore and simulated
    camera devices.
    """
    logging.getLogger("redsun").setLevel(logging.DEBUG)

    class _AcquisitionApp(QtAppContainer, config=_CONFIG):
        camera1 = component(MMCoreCameraDevice, layer="device", from_config="camera1")
        camera2 = component(SimulatedCameraDevice, layer="device", from_config="camera2")
        ctrl = component(AcquisitionController, layer="presenter", from_config="ctrl")
        widget = component(AcquisitionWidget, layer="view", from_config="widget")

    _AcquisitionApp().run()
