from __future__ import annotations

import logging

from redsun.containers.components import component
from redsun.containers.qt_container import QtAppContainer

from redsun_mimir.device.mmcore import MMCoreCameraDevice
from redsun_mimir.presenter import DetectorController
from redsun_mimir.view import DetectorWidget


class _DetectorUC2App(QtAppContainer):
    camera: MMCoreCameraDevice = component(
        layer="device",
        alias="Mimir detector",
        sensor_shape=(100, 100),
    )
    ctrl: DetectorController = component(layer="presenter", timeout=5.0)
    widget: DetectorWidget = component(layer="view")


def detector_widget_uc2() -> None:
    """Run a local UC2 example.

    Launches a Qt ``DetectorWidget`` app
    with a UC2 device configuration.
    """
    logging.getLogger("redsun").setLevel(logging.DEBUG)
    _DetectorUC2App(session="redsun-mimir").run()
