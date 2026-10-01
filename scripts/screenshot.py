"""Run `mimir sim`, start `live_stream`, and save a picture of the window.

The picture is the README's, `images/mimir-sim.png` unless another path is
given. Settings, logs and data go to a temporary folder, so nothing on this
machine changes the picture; the data folder shown is set to a neutral path,
since the temporary one names the user's profile. `QApplication.exec` is
replaced by the function taking the picture, so the session stops there and
shuts down. Run from the repository root, with the Micro-Manager demo
adapters installed (`mmcore install --test-adapters`).
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

from qtpy.QtCore import QLocale
from qtpy.QtWidgets import QApplication, QCheckBox, QMainWindow

from redsun_mimir import configurations
from redsun_mimir.view.acquisition import AcquisitionView

TARGET = Path("images/mimir-sim.png")
SIZE = (1400, 860)
SHOWN_DATA_FOLDER = "D:/mimir-data"
#: Seconds `live_stream` runs before the picture, so frames reach the viewer.
SETTLE = 4.0


def wait(app: QApplication, seconds: float) -> None:
    """Process Qt events for *seconds*."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.05)


def photograph(target: Path) -> int:
    """Start `live_stream` on the camera, save the main window to *target*, and quit."""
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    window = next(
        w for w in app.topLevelWidgets() if isinstance(w, QMainWindow) and w.isVisible()
    )
    window.resize(*SIZE)
    wait(app, 1.0)
    view = window.findChildren(AcquisitionView)[0]
    view.plans_combobox.setCurrentText("live_stream")
    page = view.plan_widgets["live_stream"]
    for box in page.group_box.findChildren(QCheckBox):
        if box.text() == "mmcamera" and not box.isChecked():
            box.click()
    wait(app, 0.5)
    page.run_button.click()
    wait(app, SETTLE)
    view.base_dir_label.setText(SHOWN_DATA_FOLDER)
    wait(app, 0.2)
    target.parent.mkdir(parents=True, exist_ok=True)
    window.grab().save(str(target))
    print(f"wrote {target}")
    page.run_button.click()
    wait(app, 2.0)
    # what quitting the event loop sends, and what shuts the session down
    app.aboutToQuit.emit()
    return 0


def main(arguments: list[str]) -> None:
    """Take the picture, to the path in *arguments* or to `TARGET`."""
    target = Path(arguments[0] if arguments else TARGET).resolve()
    with tempfile.TemporaryDirectory() as home:

        def elsewhere(*_: object, **__: object) -> str:
            return home

        # numbers are written the same way whatever machine takes the picture
        QLocale.setDefault(QLocale(QLocale.Language.English))
        with (
            mock.patch("redsun._settings.user_config_dir", elsewhere),
            mock.patch("redsun.log.user_data_dir", elsewhere),
            mock.patch("redsun.path_provider.user_data_dir", elsewhere),
            mock.patch.object(QApplication, "exec", lambda _: photograph(target)),
        ):
            try:
                configurations.run_simulation_container()
            except SystemExit:
                pass


if __name__ == "__main__":
    main(sys.argv[1:])
