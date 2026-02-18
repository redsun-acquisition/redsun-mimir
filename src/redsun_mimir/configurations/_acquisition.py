from __future__ import annotations

import logging
from pathlib import Path

from redsun.containers import AppContainer, component

from redsun_mimir.device.microscope import SimulatedCameraDevice
from redsun_mimir.device.mmcore import MMCoreCameraDevice
from redsun_mimir.presenter import AcquisitionController
from redsun_mimir.view import AcquisitionWidget

_CONFIG = Path(__file__).parent / "mock_acquisition_configuration.yaml"


class _AcquisitionApp(AppContainer, config=_CONFIG):
    camera1: MMCoreCameraDevice = component(layer="device", from_config="camera1")
    camera2: SimulatedCameraDevice = component(layer="device", from_config="camera2")
    ctrl: AcquisitionController = component(layer="presenter", from_config="ctrl")
    widget: AcquisitionWidget = component(layer="view", from_config="widget")


def acquisition_widget() -> None:
    """Run a local mock example.

    Launches a Qt ``AcquisitionWidget`` app
    with a mock device configuration.
    """
    logging.getLogger("redsun").setLevel(logging.DEBUG)
    _AcquisitionApp().run()
