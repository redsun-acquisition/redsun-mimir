from __future__ import annotations

import logging
from pathlib import Path

from redsun.containers import device, presenter, view
from redsun.qt import QtAppContainer

_CONFIG = Path(__file__).parent / "microscope_light_configuration.yaml"


def run_microscope_light_container() -> None:
    """Run a simulated microscope light source example.

    Launches a Qt ``LightView`` app with a ``SimulatedLightDevice``
    modelling a 532 nm laser.
    """
    from redsun_mimir.device.microscope import SimulatedLightDevice
    from redsun_mimir.presenter import LightPresenter
    from redsun_mimir.view import LightView

    logging.getLogger("redsun").setLevel(logging.DEBUG)

    class MicroscopeLightApp(QtAppContainer, config=_CONFIG):
        laser = device(SimulatedLightDevice, from_config="laser")
        ctrl = presenter(LightPresenter, from_config="ctrl")
        widget = view(LightView, from_config="widget")

    MicroscopeLightApp().run()
