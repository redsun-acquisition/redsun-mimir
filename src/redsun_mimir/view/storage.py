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

    Owns the application-level :class:`~redsun.storage.SessionPathProvider`
    and writes a :class:`~redsun.storage.StorageInfo` onto the
    :class:`~redsun.virtual.VirtualContainer` so that plans can read it
    via ``container.storage_info`` at launch time.

    The view exposes two editable fields:

    * **Base directory** — root path under which all output data is written.
      Defaults to ``~/redsun-storage``.  A folder-picker button opens a
      native dialog.
    * **Session** — sub-folder name appended after the base directory.
      Defaults to ``"default"``.

    Any change to either field immediately updates ``container.storage_info``
    so the next plan launch picks up the new URI.

    Parameters
    ----------
    name : str
        Identity key of the view.
    **kwargs :
        Forwarded to :class:`~redsun.view.qt.QtView`.
    """

    @property
    def view_position(self) -> ViewPosition:
        """The position in the main view."""
        return ViewPosition.LEFT

    def __init__(self, name: str, /, **kwargs: Any) -> None:
        super().__init__(name)

        _base_dir = Path.home() / "redsun-storage"
        self._provider = SessionPathProvider(base_dir=_base_dir)
        self._storage_info = StorageInfo(uri=_base_dir.as_uri())

        # --- base directory row ---
        self._base_dir_edit = QtW.QLineEdit(str(_base_dir))
        self._base_dir_edit.setReadOnly(True)
        self._base_dir_btn = QtW.QPushButton("Browse…")
        self._base_dir_btn.clicked.connect(self._on_browse_clicked)

        base_dir_row = QtW.QHBoxLayout()
        base_dir_row.addWidget(self._base_dir_edit)
        base_dir_row.addWidget(self._base_dir_btn)

        # --- session row ---
        self._session_edit = QtW.QLineEdit(self._provider.session)
        self._session_edit.editingFinished.connect(self._on_session_changed)

        # --- form layout ---
        form = QtW.QFormLayout()
        form.addRow("Output directory", base_dir_row)
        form.addRow("Session", self._session_edit)

        root = QtW.QVBoxLayout(self)
        root.addLayout(form)
        root.addStretch()
        self.setLayout(root)

        self.logger.info(f"Initialized with base dir: {_base_dir}")

    # ------------------------------------------------------------------
    # QtView lifecycle
    # ------------------------------------------------------------------

    def register_providers(self, container: VirtualContainer) -> None:
        """Write the initial StorageInfo onto the container."""
        container.storage_info = self._storage_info
        container.register_signals(self)

    def inject_dependencies(self, container: VirtualContainer) -> None:
        """Store container reference for later updates."""
        self._container = container

    # ------------------------------------------------------------------
    # Internal slots
    # ------------------------------------------------------------------

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

    def _on_session_changed(self) -> None:
        """Apply the session name typed by the user."""
        session = self._session_edit.text().strip()
        if not session or session == self._provider.session:
            return
        self._provider.session = session
        self._push_storage_info()
        self.logger.info(f"Session updated to: {session!r}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _update_base_dir(self, base_dir: Path) -> None:
        self._provider.base_dir = base_dir
        self._base_dir_edit.setText(str(base_dir))
        self._push_storage_info()
        self.logger.info(f"Base dir updated to: {base_dir}")

    def _push_storage_info(self) -> None:
        """Rebuild StorageInfo from current provider state and push to container."""
        self._storage_info = StorageInfo(uri=self._provider.base_dir.as_uri())
        self._container.storage_info = self._storage_info

    def next_storage_info(self, plan_name: str) -> StorageInfo:
        """Return a fresh :class:`~redsun.storage.StorageInfo` for one acquisition.

        Advances the per-plan counter and returns a new
        :class:`~redsun.storage.StorageInfo` with a unique, session-scoped
        URI.  Should be called by the plan body exactly once per stream event.

        Parameters
        ----------
        plan_name :
            Name of the plan (e.g. ``"live_stream"``).

        Returns
        -------
        StorageInfo
            Fresh instance with a unique URI and empty devices dict.
        """
        uri = self._provider(plan_name).store_uri
        return StorageInfo(uri=uri)
