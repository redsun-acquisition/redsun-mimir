from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from qtpy import QtWidgets
from sunflare.config import RedSunSessionInfo
from sunflare.virtual import VirtualBus

from redsun_mimir.widget import ImageWidget


def image_widget() -> None:
    """Run a local mock example.

    Launches a Qt ``ImageWidget`` app
    with a mock device configuration.
    """
    logger = logging.getLogger("redsun")
    logger.setLevel(logging.DEBUG)

    app = QtWidgets.QApplication([])

    config_path = Path(__file__).parent / "mock_image_configuration.yaml"
    config_dict: dict[str, Any] = RedSunSessionInfo.load_yaml(str(config_path))

    config = RedSunSessionInfo(
        session=config_dict["session"],
        engine=config_dict["engine"],
        frontend=config_dict["frontend"],
    )

    bus = VirtualBus()

    widget = ImageWidget(config, bus)
    widget.registration_phase()
    widget.connection_phase()

    widget.show()

    app.exec()

    bus.shutdown()
