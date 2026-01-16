from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from psygnal.qt import start_emitting_from_queue
from qtpy import QtCore, QtWidgets
from sunflare.config import PPresenterInfo, PViewInfo, RedSunSessionInfo
from sunflare.virtual import VirtualBus

from redsun_mimir.model import DetectorModelInfo, MockMotorModel, MotorModelInfo
from redsun_mimir.model.microscope import SimulatedCameraModel
from redsun_mimir.model.mmcore import MMCoreCameraModel, MMCoreCameraModelInfo
from redsun_mimir.presenter import (
    AcquisitionController,
    AcquisitionControllerInfo,
    DetectorController,
    DetectorControllerInfo,
)
from redsun_mimir.view import (
    AcquisitionWidget,
    AcquisitionWidgetInfo,
    DetectorWidget,
    DetectorWidgetInfo,
)

if TYPE_CHECKING:
    from sunflare.config import PModelInfo
    from sunflare.model import PModel


def acquisition_detector_widget() -> None:
    """Run a local mock example.

    Launches a Qt ``AcquisitionWidget`` app
    with a mock device configuration.

    Adds a background ``DetectorController``.
    """
    logger = logging.getLogger("redsun")
    logger.setLevel(logging.DEBUG)

    app = QtWidgets.QApplication([])

    config_path = Path(__file__).parent / "acquisition_detector_config.yaml"
    config_dict: dict[str, Any] = RedSunSessionInfo.load_yaml(str(config_path))
    models_info: dict[str, PModelInfo] = {}

    for name, values in config_dict["models"].items():
        if "mmcore" in name:
            models_info[name] = MMCoreCameraModelInfo(**values)
        elif "microscope" in name:
            models_info[name] = DetectorModelInfo(**values)
        elif "motor" in name:
            models_info[name] = MotorModelInfo(**values)
        else:
            raise ValueError(f"Unknown model name: {name}")
    ctrl_info: dict[str, PPresenterInfo] = {}
    widget_info: dict[str, PViewInfo] = {}

    for name, values in config_dict["controllers"].items():
        if name == "DetectorController":
            ctrl_info[name] = DetectorControllerInfo(**values)
        elif name == "AcquisitionController":
            ctrl_info[name] = AcquisitionControllerInfo(**values)

    for name, values in config_dict["views"].items():
        if name == "DetectorWidget":
            widget_info[name] = DetectorWidgetInfo(**values)
        elif name == "AcquisitionWidget":
            widget_info[name] = AcquisitionWidgetInfo(**values)

    config = RedSunSessionInfo(
        session=config_dict["session"],
        frontend=config_dict["frontend"],
        models=models_info,
        controllers=ctrl_info,
        views=widget_info,
    )

    mock_models: dict[str, PModel] = {}
    for name, model_info in models_info.items():
        if "mmcore" in name:
            mock_models[name] = MMCoreCameraModel(name, model_info)  # type: ignore
        elif "microscope" in name:
            mock_models[name] = SimulatedCameraModel(name, model_info)  # type: ignore
        elif "motor" in name:
            mock_models[name] = MockMotorModel(name, model_info)  # type: ignore
        else:
            raise ValueError(f"Unknown model name: {name}")

    bus = VirtualBus()

    acq_ctrl = AcquisitionController(
        config.controllers["AcquisitionController"],  # type: ignore
        mock_models,
        bus,
    )

    acq_widget = AcquisitionWidget(config.views["AcquisitionWidget"], bus)

    det_ctrl = DetectorController(
        config.controllers["DetectorController"],  # type: ignore
        mock_models,
        bus,
    )

    det_widget = DetectorWidget(config.views["DetectorWidget"], bus)  # type: ignore

    acq_ctrl.registration_phase()
    det_ctrl.registration_phase()
    acq_widget.registration_phase()
    det_widget.registration_phase()

    acq_ctrl.connection_phase()
    det_ctrl.connection_phase()
    acq_widget.connection_phase()
    det_widget.connection_phase()

    window = QtWidgets.QMainWindow()
    window.setCentralWidget(acq_widget)
    det_widget_dock = QtWidgets.QDockWidget("Detector Control")
    det_widget_dock.setWidget(det_widget)
    window.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, det_widget_dock)
    window.setWindowTitle("Acquisition widget")
    window.adjustSize()
    window.show()

    start_emitting_from_queue()
    app.exec()
