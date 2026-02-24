from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from qtpy import QtWidgets as QtW
from redsun.log import Loggable
from redsun.storage import SessionPathProvider, StorageInfo
from redsun.view import ViewPosition
from redsun.view.qt import QtView

if TYPE_CHECKING:
    from redsun.virtual import VirtualContainer


class FileStorageView(QtView, Loggable):
    """View for configuring the output storage location.

    Parameters
    ----------
    name : str
        Identity key of the view.
    **kwargs : Any
        Additional keyword arguments (unused).
    """

    @property
    def view_position(self) -> ViewPosition:
        """The position in the main view."""
        return ViewPosition.LEFT

    def __init__(self, name: str, /, **kwargs: Any) -> None:
        super().__init__(name, **kwargs)

        _base_dir = Path.home() / "redsun-storage"
        self._provider = SessionPathProvider(base_dir=_base_dir)
        self._storage_info = StorageInfo(uri=_base_dir.as_uri())

        self._base_dir_edit = QtW.QLineEdit(str(_base_dir))
        self._base_dir_edit.setReadOnly(True)
        self._base_dir_btn = QtW.QPushButton("Browse...")
        self._base_dir_btn.clicked.connect(self._on_browse_clicked)

        base_dir_row = QtW.QHBoxLayout()
        base_dir_row.addWidget(self._base_dir_edit)
        base_dir_row.addWidget(self._base_dir_btn)

        form = QtW.QFormLayout()
        form.addRow("Root directory", base_dir_row)

        root = QtW.QVBoxLayout(self)
        root.addLayout(form)
        root.addStretch()
        self.setLayout(root)

        self.logger.info(f"Initialized with base dir: {_base_dir}")

    def register_providers(self, container: VirtualContainer) -> None:
        """Write the initial StorageInfo onto the container."""
        self._container = container
        self._provider.session = container.session
        container.storage_info = self._storage_info
        container.register_signals(self)

    def _on_browse_clicked(self) -> None:
        """Open a native folder-picker and update the base directory."""
        chosen = QtW.QFileDialog.getExistingDirectory(
            self,
            "Select output directory",
            str(self._provider.base_dir),
        )
        if not chosen:
            return
        self._update_base_dir(Path(chosen))

    def _update_base_dir(self, base_dir: Path) -> None:
        self._provider.base_dir = base_dir
        self._base_dir_edit.setText(str(base_dir))
        self._push_storage_info()
        self.logger.info(f"Base dir updated to: {base_dir}")

    def _push_storage_info(self) -> None:
        """Rebuild StorageInfo from current provider state and push to container."""
        self._storage_info = StorageInfo(uri=self._provider.base_dir.as_uri())
        self._container.storage_info = self._storage_info
