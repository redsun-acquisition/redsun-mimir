from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from psygnal.qt import start_emitting_from_queue
from qtpy import QtWidgets
from sunflare.config import RedSunSessionInfo
from sunflare.virtual import VirtualBus

from redsun_mimir.controller import DetectorControllerInfo, ImageController
from redsun_mimir.model import DetectorModelInfo
from redsun_mimir.model.microscope import SimulatedCameraModel
from redsun_mimir.widget import ImageWidget, ImageWidgetInfo


def image_widget() -> None:
    """Run a local mock example.

    Launches a Qt ``DetectorWidget`` app
    with a mock device configuration.
    """
    logger = logging.getLogger("redsun")
    logger.setLevel(logging.DEBUG)

    app = QtWidgets.QApplication([])

    config_path = Path(__file__).parent / "mock_detector_configuration.yaml"
    config_dict: dict[str, Any] = RedSunSessionInfo.load_yaml(str(config_path))
    models_info: dict[str, DetectorModelInfo] = {
        name: DetectorModelInfo(**values)
        for name, values in config_dict["models"].items()
    }
    ctrl_info: dict[str, DetectorControllerInfo] = {
        name: DetectorControllerInfo(**values)
        for name, values in config_dict["controllers"].items()
    }
    widget_info: dict[str, ImageWidgetInfo] = {
        name: ImageWidgetInfo(**values) for name, values in config_dict["views"].items()
    }

    config = RedSunSessionInfo(
        session=config_dict["session"],
        engine=config_dict["engine"],
        frontend=config_dict["frontend"],
        models=models_info,  # type: ignore
        controllers=ctrl_info,  # type: ignore
        views=widget_info,  # type: ignore
    )

    mock_models: dict[str, SimulatedCameraModel] = {
        name: SimulatedCameraModel(name, model_info)
        for name, model_info in models_info.items()
    }

    bus = VirtualBus()

    ctrl = ImageController(
        config.controllers["ImageController"],  # type: ignore
        mock_models,
        bus,
    )
    widget = ImageWidget(config.views["ImageWidget"], bus)

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
