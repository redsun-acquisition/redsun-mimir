from __future__ import annotations

import logging
from pathlib import Path

from redsun.containers import component
from redsun.qt import QtAppContainer

_CONFIG = Path(__file__).parent / "uc2_detector_configuration.yaml"


def detector_widget_uc2() -> None:
    """Run a UC2 detector example.

    Launches a Qt ``DetectorView`` app with an MMCore camera device.
    """
    from redsun_mimir.device.mmcore import MMCoreCameraDevice
    from redsun_mimir.presenter import DetectorPresenter
    from redsun_mimir.view import DetectorView

    logging.getLogger("redsun").setLevel(logging.DEBUG)

    class DetectorUC2App(QtAppContainer, config=_CONFIG):
        camera = component(MMCoreCameraDevice, layer="device", from_config="camera")
        ctrl = component(DetectorPresenter, layer="presenter", from_config="ctrl")
        widget = component(DetectorView, layer="view", from_config="widget")

    DetectorUC2App().run()
