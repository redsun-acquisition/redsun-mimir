from __future__ import annotations

import logging
from pathlib import Path

from redsun.containers import AppContainer, component

from redsun_mimir.device.mmcore import MMCoreCameraDevice
from redsun_mimir.presenter import AcquisitionController
from redsun_mimir.view import AcquisitionWidget

_CONFIG = Path(__file__).parent / "uc2_acquisition_configuration.yaml"


class _AcquisitionUC2App(AppContainer, config=_CONFIG):
    camera = component(MMCoreCameraDevice, layer="device", from_config="camera")
    ctrl = component(AcquisitionController, layer="presenter", from_config="ctrl")
    widget = component(AcquisitionWidget, layer="view", from_config="widget")


def acquisition_widget_uc2() -> None:
    """Run a local UC2 example.

    Launches a Qt ``AcquisitionWidget`` app
    with a UC2 device configuration.
    """
    logging.getLogger("redsun").setLevel(logging.DEBUG)
    _AcquisitionUC2App().run()
