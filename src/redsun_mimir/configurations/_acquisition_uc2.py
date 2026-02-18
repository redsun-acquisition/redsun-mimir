from __future__ import annotations

import logging
from pathlib import Path

from redsun.containers import component
from redsun.qt import QtAppContainer

_CONFIG = Path(__file__).parent / "uc2_acquisition_configuration.yaml"


def acquisition_widget_uc2() -> None:
    """Run a UC2 acquisition example.

    Launches a Qt ``AcquisitionView`` app with a UC2 MMCore camera device.
    """
    from redsun_mimir.device.mmcore import MMCoreCameraDevice
    from redsun_mimir.presenter import AcquisitionPresenter
    from redsun_mimir.view import AcquisitionView

    logging.getLogger("redsun").setLevel(logging.DEBUG)

    class AcquisitionUC2App(QtAppContainer, config=_CONFIG):
        camera = component(MMCoreCameraDevice, layer="device", from_config="camera")
        ctrl = component(AcquisitionPresenter, layer="presenter", from_config="ctrl")
        widget = component(AcquisitionView, layer="view", from_config="widget")

    AcquisitionUC2App().run()
