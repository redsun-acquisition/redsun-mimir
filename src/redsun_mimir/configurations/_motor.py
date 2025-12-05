from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from psygnal.qt import start_emitting_from_queue
from qtpy import QtWidgets
from sunflare.config import RedSunSessionInfo
from sunflare.virtual import VirtualBus

from redsun_mimir.controller import MotorController, MotorControllerInfo
from redsun_mimir.model import MockMotorModel, MotorModelInfo
from redsun_mimir.view import MotorWidget, MotorWidgetInfo


def stage_widget() -> None:
    """Run a local mock example.

    Launches a Qt ``MotorWidget`` app
    with a mock device configuration.
    """
    logger = logging.getLogger("redsun")
    logger.setLevel(logging.DEBUG)
    app = QtWidgets.QApplication([])

    mock_config_path = "mock_motor_configuration.yaml"

    config_path = Path(__file__).parent / mock_config_path
    config_dict: dict[str, Any] = RedSunSessionInfo.load_yaml(str(config_path))
    models_info: dict[str, MotorModelInfo] = {
        name: MotorModelInfo(**values) for name, values in config_dict["models"].items()
    }
    ctrl_info: dict[str, MotorControllerInfo] = {
        name: MotorControllerInfo(**values)
        for name, values in config_dict["controllers"].items()
    }
    widget_info: dict[str, MotorWidgetInfo] = {
        name: MotorWidgetInfo(**values) for name, values in config_dict["views"].items()
    }

    config = RedSunSessionInfo(
        session=config_dict["session"],
        frontend=config_dict["frontend"],
        models=models_info,  # type: ignore
        controllers=ctrl_info,  # type: ignore
        views=widget_info,  # type: ignore
    )

    mock_models: dict[str, MockMotorModel] = {
        name: MockMotorModel(name, model_info)
        for name, model_info in models_info.items()
    }

    bus = VirtualBus()

    ctrl = MotorController(config.controllers["MotorController"], mock_models, bus)  # type: ignore[arg-type]
    widget = MotorWidget(config.views["MotorWidget"], bus)

    ctrl.registration_phase()
    widget.registration_phase()
    ctrl.connection_phase()
    widget.connection_phase()

    window = QtWidgets.QMainWindow()
    window.setCentralWidget(widget)
    window.show()

    start_emitting_from_queue()
    app.exec()

    bus.shutdown()
