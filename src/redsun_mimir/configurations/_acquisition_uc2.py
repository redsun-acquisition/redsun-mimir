from __future__ import annotations

import logging
from pathlib import Path

from redsun.containers import component
from redsun.qt import QtAppContainer

from redsun_mimir.device.mmcore import MMCoreCameraDevice
from redsun_mimir.presenter import AcquisitionController
from redsun_mimir.view import AcquisitionWidget

_CONFIG = Path(__file__).parent / "uc2_acquisition_configuration.yaml"


def acquisition_widget_uc2() -> None:
    """Run a UC2 acquisition example.

    Launches a Qt ``AcquisitionWidget`` app with a UC2 MMCore camera device.
    """
    logging.getLogger("redsun").setLevel(logging.DEBUG)

    class _AcquisitionUC2App(QtAppContainer, config=_CONFIG):
        camera = component(MMCoreCameraDevice, layer="device", from_config="camera")
        ctrl = component(AcquisitionController, layer="presenter", from_config="ctrl")
        widget = component(AcquisitionWidget, layer="view", from_config="widget")

    _AcquisitionUC2App().run()
