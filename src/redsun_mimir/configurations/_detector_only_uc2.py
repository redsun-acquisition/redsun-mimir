from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from psygnal.qt import start_emitting_from_queue
from qtpy import QtWidgets
from sunflare.config import RedSunSessionInfo
from sunflare.virtual import VirtualBus

from redsun_mimir.controller import DetectorController, DetectorControllerInfo
from redsun_mimir.model import DetectorModelInfo
from redsun_mimir.model.youseetoo import MimirDetectorModel
from redsun_mimir.widget import DetectorWidget, DetectorWidgetInfo


def detector_widget_uc2() -> None:
    """Run a local UC2 example.

    Launches a Qt ``DetectorWidget`` app
    with a UC2 device configuration.
    """
    logger = logging.getLogger("redsun")
    logger.setLevel(logging.DEBUG)

    app = QtWidgets.QApplication([])

    config_path = Path(__file__).parent / "uc2_image_configuration.yaml"
    config_dict: dict[str, Any] = RedSunSessionInfo.load_yaml(str(config_path))
    models_info: dict[str, DetectorModelInfo] = {
        name: DetectorModelInfo(**values)
        for name, values in config_dict["models"].items()
    }
    ctrl_info: dict[str, DetectorControllerInfo] = {
        name: DetectorControllerInfo(**values)
        for name, values in config_dict["controllers"].items()
    }
    widget_info: dict[str, DetectorWidgetInfo] = {
        name: DetectorWidgetInfo(**values)
        for name, values in config_dict["views"].items()
    }

    config = RedSunSessionInfo(
        session=config_dict["session"],
        frontend=config_dict["frontend"],
        models=models_info,  # type: ignore
        controllers=ctrl_info,  # type: ignore
        views=widget_info,  # type: ignore
    )

    mock_models: dict[str, MimirDetectorModel] = {
        name: MimirDetectorModel(name, model_info)
        for name, model_info in models_info.items()
    }

    bus = VirtualBus()

    ctrl = DetectorController(
        config.controllers["DetectorController"],  # type: ignore
        mock_models,
        bus,
    )
    widget = DetectorWidget(config.views["DetectorWidget"], bus)  # type: ignore

    ctrl.registration_phase()
    widget.registration_phase()
    ctrl.connection_phase()
    widget.connection_phase()

    window = QtWidgets.QMainWindow()
    window.setCentralWidget(widget)
    window.setWindowTitle("Image widget")
    window.resize(800, 600)
    window.show()

    start_emitting_from_queue()
    app.exec()

    bus.shutdown()
