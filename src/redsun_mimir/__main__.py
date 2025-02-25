from pathlib import Path
from typing import Any

from psygnal.qt import start_emitting_from_queue
from qtpy import QtWidgets
from sunflare.config import RedSunSessionInfo
from sunflare.virtual import VirtualBus

from redsun_mimir.controller import StageController, StageControllerInfo
from redsun_mimir.model import MockStageModel, StageModelInfo
from redsun_mimir.widget import StageWidget, StageWidgetInfo


def main() -> None:
    """Run a local mock example."""
    app = QtWidgets.QApplication([])

    config_path = (
        Path(__file__).parent.parent.parent
        / "tests"
        / "data"
        / "mock_configuration.yaml"
    )
    config_dict: dict[str, Any] = RedSunSessionInfo.load_yaml(str(config_path))
    models_info: dict[str, StageModelInfo] = {
        name: StageModelInfo(**values) for name, values in config_dict["models"].items()
    }
    ctrl_info: dict[str, StageControllerInfo] = {
        name: StageControllerInfo(**values)
        for name, values in config_dict["controllers"].items()
    }
    widget_info: dict[str, StageWidgetInfo] = {
        name: StageWidgetInfo(**values)
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

    mock_models: dict[str, MockStageModel] = {
        name: MockStageModel(name, model_info)
        for name, model_info in models_info.items()
    }

    bus = VirtualBus()

    ctrl = StageController(config.controllers["StageController"], mock_models, bus)  # type: ignore
    widget = StageWidget(config, bus)

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


if __name__ == "__main__":
    main()
