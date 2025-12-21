from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from psygnal.qt import start_emitting_from_queue
from qtpy import QtWidgets
from sunflare.config import RedSunSessionInfo
from sunflare.virtual import VirtualBus

from redsun_mimir.model.youseetoo import (
    MimirLaserInfo,
    MimirLaserModel,
    MimirSerialModel,
    MimirSerialModelInfo,
)
from redsun_mimir.presenter import LightController, LightControllerInfo
from redsun_mimir.view import LightWidget, LightWidgetInfo


def light_widget_uc2() -> None:
    """Run a local UC2 example.

    Launches a Qt ``LightWidget`` app
    with a UC2 device configuration.
    """
    logger = logging.getLogger("redsun")
    logger.setLevel(logging.DEBUG)

    app = QtWidgets.QApplication([])

    config_path = Path(__file__).parent / "uc2_light_configuration.yaml"
    config_dict: dict[str, Any] = RedSunSessionInfo.load_yaml(str(config_path))

    models_info: dict[str, MimirLaserInfo | MimirSerialModelInfo] = {}

    for name, values in config_dict["models"].items():
        if name == "Serial":
            models_info[name] = MimirSerialModelInfo(**values)
        elif name == "Laser 1":
            models_info[name] = MimirLaserInfo(**values)

    ctrl_info: dict[str, LightControllerInfo] = {
        name: LightControllerInfo(**values)
        for name, values in config_dict["controllers"].items()
    }
    widget_info: dict[str, LightWidgetInfo] = {
        name: LightWidgetInfo(**values) for name, values in config_dict["views"].items()
    }

    config = RedSunSessionInfo(
        session=config_dict["session"],
        frontend=config_dict["frontend"],
        models=models_info,  # type: ignore
        controllers=ctrl_info,  # type: ignore
        views=widget_info,  # type: ignore
    )

    models: dict[str, MimirLaserModel | MimirSerialModel] = {
        name: MimirSerialModel(name, model_info)
        if isinstance(model_info, MimirSerialModelInfo)
        else MimirLaserModel(name, model_info)
        for name, model_info in models_info.items()
    }

    bus = VirtualBus()

    ctrl = LightController(config.controllers["LightController"], models, bus)  # type: ignore
    widget = LightWidget(config.views["LightWidget"], bus)

    ctrl.registration_phase()
    widget.registration_phase()
    ctrl.connection_phase()
    widget.connection_phase()

    window = QtWidgets.QMainWindow()
    window.setCentralWidget(widget)
    window.show()

    start_emitting_from_queue()
    app.exec()
