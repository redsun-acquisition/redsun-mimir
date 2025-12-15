from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from psygnal.qt import start_emitting_from_queue
from qtpy import QtCore, QtWidgets
from sunflare.config import PPresenterInfo, PViewInfo, RedSunSessionInfo
from sunflare.virtual import VirtualBus

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
    models_info: dict[str, MMCoreCameraModelInfo] = {
        name: MMCoreCameraModelInfo(**values)
        for name, values in config_dict["models"].items()
    }
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
        models=models_info,  # type: ignore
        controllers=ctrl_info,
        views=widget_info,
    )

    mock_models: dict[str, PModel] = {
        name: MMCoreCameraModel(name, model_info)
        for name, model_info in models_info.items()
    }

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

    bus.shutdown()
