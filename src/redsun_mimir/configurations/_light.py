from __future__ import annotations

import logging
from pathlib import Path

from redsun.containers import declare_device, declare_presenter, declare_view
from redsun.qt import QtAppContainer

_CONFIG = Path(__file__).parent / "light_configuration.yaml"


def run_light_container() -> None:
    """Run a local mock light example.

    Launches a Qt ``LightView`` app with a mock light device.
    """
    from redsun_mimir.device import MockLightDevice
    from redsun_mimir.presenter.light import LightPresenter
    from redsun_mimir.view.light import LightView

    logging.getLogger("redsun").setLevel(logging.DEBUG)

    class LightApp(QtAppContainer, config=_CONFIG):
        led = declare_device(MockLightDevice, from_config="led")
        laser = declare_device(MockLightDevice, from_config="laser")
        ctrl = declare_presenter(LightPresenter, from_config="light_ctrl")
        widget = declare_view(LightView, from_config="widget")

    LightApp().run()
