from pathlib import Path
from typing import Any

from psygnal.qt import start_emitting_from_queue
from qtpy import QtWidgets
from sunflare.config import RedSunSessionInfo
from sunflare.virtual import VirtualBus

from redsun_mimir.controller import LightController, LightControllerInfo
from redsun_mimir.model import LightModelInfo, MockLightModel
from redsun_mimir.widget import LightWidget, LightWidgetInfo


def light_widget() -> None:
    """Run a local mock example.

    Launches a Qt ``LightWidget`` app
    with a mock device configuration.
    """
    app = QtWidgets.QApplication([])

    config_path = Path(__file__).parent / "mock_light_configuration.yaml"
    config_dict: dict[str, Any] = RedSunSessionInfo.load_yaml(str(config_path))
    models_info: dict[str, LightModelInfo] = {
        name: LightModelInfo(**values) for name, values in config_dict["models"].items()
    }
    ctrl_info: dict[str, LightControllerInfo] = {
        name: LightControllerInfo(**values)
        for name, values in config_dict["controllers"].items()
    }
    widget_info: dict[str, LightWidgetInfo] = {
        name: LightWidgetInfo(**values)
        for name, values in config_dict["widgets"].items()
    }

    config = RedSunSessionInfo(
        session=config_dict["session"],
        engine=config_dict["engine"],
        frontend=config_dict["frontend"],
        models=models_info,  # type: ignore
        controllers=ctrl_info,  # type: ignore
        widgets=widget_info,  # type: ignore
    )

    mock_models: dict[str, MockLightModel] = {
        name: MockLightModel(name, model_info)
        for name, model_info in models_info.items()
    }

    bus = VirtualBus()

    ctrl = LightController(config.controllers["LightController"], mock_models, bus)  # type: ignore
    widget = LightWidget(config, bus)

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
