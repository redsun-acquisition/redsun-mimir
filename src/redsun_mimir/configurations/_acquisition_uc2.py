from __future__ import annotations

import logging

from redsun.containers.components import component
from redsun.containers.qt_container import QtAppContainer

from redsun_mimir.device.mmcore import MMCoreCameraDevice
from redsun_mimir.presenter import AcquisitionController
from redsun_mimir.view import AcquisitionWidget


class _AcquisitionUC2App(QtAppContainer):
    camera: MMCoreCameraDevice = component(
        layer="device",
        alias="Mock1",
        sensor_shape=(100, 100),
    )
    ctrl: AcquisitionController = component(layer="presenter", timeout=5.0)
    widget: AcquisitionWidget = component(layer="view")


def acquisition_widget_uc2() -> None:
    """Run a local UC2 example.

    Launches a Qt ``AcquisitionWidget`` app
    with a UC2 device configuration.
    """
    logging.getLogger("redsun").setLevel(logging.DEBUG)
    _AcquisitionUC2App(session="redsun-mimir").run()
