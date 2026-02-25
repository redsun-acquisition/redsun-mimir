from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from dependency_injector import providers
from qtpy import QtWidgets as QtW
from redsun.log import Loggable
from redsun.storage import SessionPathProvider
from redsun.view import ViewPosition
from redsun.view.qt import QtView
from redsun.virtual import Signal

if TYPE_CHECKING:
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

    sigRootDirChanged = Signal(str)

    @property
    def view_position(self) -> ViewPosition:
        """The position in the main view."""
        return ViewPosition.LEFT

    def __init__(self, name: str, /, **kwargs: Any) -> None:
        super().__init__(name, **kwargs)

        root_directory = Path.home() / "redsun-storage"

        self._root_dir_edit = QtW.QLineEdit(str(root_directory))
        self._root_dir_edit.setReadOnly(True)
        self._root_dir_btn = QtW.QPushButton("Browse...")
        self._root_dir_btn.clicked.connect(self._on_browse_clicked)

        base_dir_row = QtW.QHBoxLayout()
        base_dir_row.addWidget(self._root_dir_edit)
        base_dir_row.addWidget(self._root_dir_btn)

        self._writers_list = QtW.QListWidget()
        self._writers_list.setSelectionMode(
            QtW.QAbstractItemView.SelectionMode.NoSelection
        )
        self._refresh_btn = QtW.QPushButton("Refresh writers")
        self._refresh_btn.clicked.connect(self._refresh_writers)

        writers_header = QtW.QLabel("Registered writer groups")
        writers_header.setStyleSheet("font-weight: bold;")

        # --- layout ---
        form = QtW.QFormLayout()
        form.addRow("Root directory", base_dir_row)

        root = QtW.QVBoxLayout(self)
        root.addLayout(form)
        root.addWidget(writers_header)
        root.addWidget(self._writers_list)
        root.addWidget(self._refresh_btn)
        root.addStretch()
        self.setLayout(root)

        self.logger.info(f"Initialized with base dir: {root_directory}")

    def register_providers(self, container: VirtualContainer) -> None:
        """Push the current root directory as path onto the container."""
        container.root_dir = providers.Object(Path(self._root_dir_edit.text()))
        container.path_provider = providers.Object(
            SessionPathProvider(
                base_dir=Path(self._root_dir_edit.text()), session=container.session
            )
        )

    def inject_dependencies(self, container: VirtualContainer) -> None:
        """Get the available writers, grouped by mimetype."""
        self.available_writers: dict[str, list[str]] | None = (
            container.available_writers()
        )
        if self.available_writers is None:
            self.logger.warning("No available writers found.")
        self._refresh_writers()

    def _on_browse_clicked(self) -> None:
        """Open a native folder-picker and update the base directory."""
        chosen = QtW.QFileDialog.getExistingDirectory(
            self,
            "Select output directory",
            self._root_dir_edit.text(),
        )
        if not chosen:
            return
        self._update_base_dir(chosen)

    def _update_base_dir(self, base_dir: str) -> None:
        self.sigRootDirChanged.emit(base_dir)
        self._root_dir_edit.setText(base_dir)

    def _refresh_writers(self) -> None:
        """Repopulate the writer groups list from the current registry."""
        self._writers_list.clear()
        if not self.available_writers:
            self._writers_list.addItem("(no writers registered)")
            return
        for mimetype, groups in sorted(self.available_writers.items()):
            for group_name in sorted(groups):
                self._writers_list.addItem(f"{group_name}  [{mimetype}]")
