from __future__ import annotations

import logging
from pathlib import Path

from redsun.containers import AppContainer, component

from redsun_mimir.device.mmcore import MMCoreCameraDevice
from redsun_mimir.presenter import DetectorController
from redsun_mimir.view import DetectorWidget

_CONFIG = Path(__file__).parent / "mock_detector_configuration.yaml"


class _DetectorApp(AppContainer, config=_CONFIG):
    camera = component(MMCoreCameraDevice, layer="device", from_config="camera")
    ctrl = component(DetectorController, layer="presenter", from_config="ctrl")
    widget = component(DetectorWidget, layer="view", from_config="widget")


def detector_widget() -> None:
    """Run a local mock example.

    Launches a Qt ``DetectorWidget`` app
    with a mock device configuration.
    """
    logging.getLogger("redsun").setLevel(logging.DEBUG)
    _DetectorApp().run()
