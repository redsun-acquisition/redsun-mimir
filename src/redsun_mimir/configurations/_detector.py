from __future__ import annotations

import logging

from redsun.containers.components import component
from redsun.containers.qt_container import QtAppContainer

from redsun_mimir.device.mmcore import MMCoreCameraDevice
from redsun_mimir.presenter import DetectorController
from redsun_mimir.view import DetectorWidget


class _DetectorApp(QtAppContainer):
    camera: MMCoreCameraDevice = component(
        layer="device",
        alias="Mock1",
        sensor_shape=(100, 100),
    )
    ctrl: DetectorController = component(layer="presenter", timeout=5.0)
    widget: DetectorWidget = component(layer="view")


def detector_widget() -> None:
    """Run a local mock example.

    Launches a Qt ``DetectorWidget`` app
    with a mock device configuration.
    """
    logging.getLogger("redsun").setLevel(logging.DEBUG)
    _DetectorApp(session="redsun-mimir").run()
