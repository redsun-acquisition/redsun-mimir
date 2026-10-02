from __future__ import annotations

from typing import TYPE_CHECKING

from qtpy import QtCore, QtGui, QtWidgets
from redsun.qt import MenuItem
from redsun.view.qt.builtins import LogView

if TYPE_CHECKING:
    from redsun import Placement

#: Size a log window opens at, in pixels.
WINDOW_SIZE = (900, 500)


class LogsAction(QtGui.QAction):
    """The Logs entry of the View menu, showing the session's log in a window.

    The window is made when the entry is chosen and deleted when it is
    closed; it shows every record the log buffer still holds. Choosing the
    entry while the window is open brings it to the front.
    """

    placement: Placement = MenuItem("View")

    def __init__(self, name: str, parent: QtWidgets.QWidget) -> None:
        super().__init__("Logs", parent)
        self.name = name
        self._owner = parent
        self._window: LogView | None = None
        self.triggered.connect(self.show_logs)

    def show_logs(self) -> None:
        """Open the log window, or bring the open one to the front."""
        if self._window is None:
            window = LogView(self.name, self._owner)
            window.setWindowFlag(QtCore.Qt.WindowType.Window)
            window.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
            window.setWindowTitle("Logs")
            window.resize(*WINDOW_SIZE)
            window.destroyed.connect(self._on_window_destroyed)
            self._window = window
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()

    def _on_window_destroyed(self) -> None:
        self._window = None
