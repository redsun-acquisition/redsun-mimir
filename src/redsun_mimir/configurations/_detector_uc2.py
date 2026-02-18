from __future__ import annotations

import logging
from pathlib import Path

from redsun.containers import component
from redsun.containers.qt_container import QtAppContainer

from redsun_mimir.device.mmcore import MMCoreCameraDevice
from redsun_mimir.presenter import DetectorController
from redsun_mimir.view import DetectorWidget

_CONFIG = Path(__file__).parent / "uc2_image_configuration.yaml"


class _DetectorUC2App(QtAppContainer, config=_CONFIG):
    camera: MMCoreCameraDevice = component(layer="device", from_config="camera")
    ctrl: DetectorController = component(layer="presenter", from_config="ctrl")
    widget: DetectorWidget = component(layer="view", from_config="widget")


def detector_widget_uc2() -> None:
    """Run a local UC2 example.

    Launches a Qt ``DetectorWidget`` app
    with a UC2 device configuration.
    """
    logging.getLogger("redsun").setLevel(logging.DEBUG)
    _DetectorUC2App().run()
