from __future__ import annotations

from typing import TYPE_CHECKING, Any

from qtpy import QtWidgets as QtW
from qtpy.QtCore import QUrl
from qtpy.QtGui import QDesktopServices
from redsun.aio import run_coro
from redsun.log import Loggable
from redsun.view import ViewPosition
from redsun.view.qt import QtView

from redsun_mimir.storage import get_path_provider

if TYPE_CHECKING:
    from bluesky.protocols import Reading
    from redsun.virtual import VirtualContainer


class FileStorageView(QtView, Loggable):
    """View for configuring the output storage location.

    Displays the root output directory and the currently registered
    writer groups, grouped by mimetype.  The path provider is pushed
    onto the container so that a presenter can call it
    at acquisition time to generate per-writer URIs of the form:

        <base_dir>/<session>/<date>/<plan_key>_<group>_<counter>

    Parameters
    ----------
    name : str
        Identity key of the view.
    **kwargs : Any
        Additional keyword arguments (unused).

    Attributes
    ----------
    sigRootDirChanged : Signal[str]
        Emitted when the root output directory is changed by the user.
    """

    @property
    def view_position(self) -> ViewPosition:
        """The position in the main view."""
        return ViewPosition.LEFT

    def __init__(self, name: str, /, **kwargs: Any) -> None:
        super().__init__(name, **kwargs)

        self._root_dir_edit = QtW.QLineEdit()
        self._root_dir_edit.setReadOnly(True)
        self._root_dir_btn = QtW.QPushButton("Browse...")
        self._root_dir_btn.clicked.connect(self._on_browse_clicked)

        base_dir_row = QtW.QHBoxLayout()
        base_dir_row.addWidget(self._root_dir_edit)
        base_dir_row.addWidget(self._root_dir_btn)

        self._open_dir_btn = QtW.QPushButton("Open root directory")
        self._open_dir_btn.clicked.connect(self._on_open_dir_clicked)

        form = QtW.QFormLayout()
        form.addRow("Root directory", base_dir_row)

        root = QtW.QVBoxLayout(self)
        root.addLayout(form)
        root.addWidget(self._open_dir_btn)
        root.addStretch()
        self.setLayout(root)
        self._provider = get_path_provider()

    def inject_dependencies(self, container: VirtualContainer) -> None:
        """Get the root directory from the presenter if available."""
        try:
            root_dir: str | None = container.root_directory()
            self._provider = container.path_provider()
            root_dir = str(self._provider.base_dir)
        except AttributeError as e:
            self.logger.warning(
                "Could not retrieve root directory from container: %s", e
            )
            root_dir = None
        self._root_dir_edit.setText(root_dir or "No root directory provided.")

        async def _wire() -> None:
            self._provider.base_dir_sig.subscribe_reading(self._on_base_dir_changed)

        run_coro(_wire())

    def _on_base_dir_changed(self, reading: dict[str, Reading[str]]) -> None:
        value = next(iter(reading.values()))["value"]
        self._root_dir_edit.setText(value)

    def _on_browse_clicked(self) -> None:
        """Open a native folder-picker and update the base directory."""
        chosen = QtW.QFileDialog.getExistingDirectory(
            self,
            "Select output directory",
            self._root_dir_edit.text(),
        )
        if not chosen:
            return

        async def _set() -> None:
            await self._provider.base_dir_sig.set(chosen)

        run_coro(_set())

    def _on_open_dir_clicked(self) -> None:
        """Open the current base directory in the system file explorer."""
        path = self._root_dir_edit.text()
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))
