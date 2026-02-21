from __future__ import annotations

import logging
from pathlib import Path

from redsun.containers import device, presenter, view
from redsun.qt import QtAppContainer

_CONFIG = Path(__file__).parent / "light_configuration.yaml"


def run_light_container() -> None:
    """Run a local mock light example.

    Launches a Qt ``LightView`` app with a mock light device.
    """
    from redsun_mimir.device import MockLightDevice
    from redsun_mimir.presenter import LightPresenter
    from redsun_mimir.view import LightView

    logging.getLogger("redsun").setLevel(logging.DEBUG)

    class LightApp(QtAppContainer, config=_CONFIG):
        led = device(MockLightDevice, from_config="led")
        laser = device(MockLightDevice, from_config="laser")
        ctrl = presenter(LightPresenter, from_config="ctrl")
        widget = view(LightView, from_config="widget")

    LightApp().run()
