from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from psygnal.qt import start_emitting_from_queue
from qtpy import QtWidgets
from sunflare.config import PModelInfo, RedSunSessionInfo
from sunflare.virtual import VirtualBus

from redsun_mimir.model import DetectorModelInfo
from redsun_mimir.model.microscope import SimulatedCameraModel
from redsun_mimir.model.mmcore import MMCoreCameraModel, MMCoreCameraModelInfo
from redsun_mimir.presenter import AcquisitionController, AcquisitionControllerInfo
from redsun_mimir.view import AcquisitionWidget, AcquisitionWidgetInfo

if TYPE_CHECKING:
    from sunflare.model import PModel


def acquisition_widget() -> None:
    """Run a local mock example.

    Launches a Qt ``AcquisitionWidget`` app
    with a mock device configuration.
    """
    logger = logging.getLogger("redsun")
    logger.setLevel(logging.DEBUG)

    app = QtWidgets.QApplication([])

    config_path = Path(__file__).parent / "mock_acquisition_configuration.yaml"
    config_dict: dict[str, Any] = RedSunSessionInfo.load_yaml(str(config_path))
    models_info: dict[str, PModelInfo] = {}

    for name, values in config_dict["models"].items():
        if name == "Mock1":
            models_info[name] = MMCoreCameraModelInfo(**values)
        elif name == "Mock2":
            models_info[name] = DetectorModelInfo(**values)
        else:
            raise ValueError(f"Unknown model name: {name}")
    ctrl_info: dict[str, AcquisitionControllerInfo] = {
        name: AcquisitionControllerInfo(**values)
        for name, values in config_dict["controllers"].items()
        if name == "AcquisitionController"
    }
    widget_info: dict[str, AcquisitionWidgetInfo] = {
        name: AcquisitionWidgetInfo(**values)
        for name, values in config_dict["views"].items()
        if name == "AcquisitionWidget"
    }

    config = RedSunSessionInfo(
        session=config_dict["session"],
        frontend=config_dict["frontend"],
        models=models_info,
        controllers=ctrl_info,  # type: ignore
        views=widget_info,  # type: ignore
    )

    mock_models: dict[str, PModel] = {}
    for name, model_info in models_info.items():
        if name == "Mock1":
            mock_models[name] = MMCoreCameraModel(name, model_info)  # type: ignore
        elif name == "Mock2":
            mock_models[name] = SimulatedCameraModel(name, model_info)  # type: ignore
        else:
            raise ValueError(f"Unknown model name: {name}")

    bus = VirtualBus()

    ctrl = AcquisitionController(
        config.controllers["AcquisitionController"],  # type: ignore
        mock_models,
        bus,
    )
    widget = AcquisitionWidget(config.views["AcquisitionWidget"], bus)

    ctrl.registration_phase()
    widget.registration_phase()
    ctrl.connection_phase()
    widget.connection_phase()

    window = QtWidgets.QMainWindow()
    window.setCentralWidget(widget)
    window.setWindowTitle("Detector Widget")
    window.adjustSize()
    window.show()

    start_emitting_from_queue()
    app.exec()
