from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from redsun.log import Loggable
from redsun.presenter import Presenter
from redsun.storage import SessionPathProvider, StorageInfo
from redsun.virtual import Signal

from redsun_mimir.utils import find_signals

if TYPE_CHECKING:
    from collections.abc import Mapping

    from redsun.device import Device
    from redsun.virtual import VirtualContainer


class FileStoragePresenter(Presenter, Loggable):
    """Presenter that owns the application-level storage location.

    Holds a [`SessionPathProvider`][redsun.storage.SessionPathProvider] and exposes a
    [`StorageInfo`][redsun.storage.StorageInfo] on the
    [`VirtualContainer`][redsun.virtual.VirtualContainer] whose ``uri`` reflects the
    current base directory.  The plan body calls
    [`next_storage_info`][redsun_mimir.presenter.storage.FileStoragePresenter.next_storage_info]
    to obtain a fresh [`StorageInfo`][redsun.storage.StorageInfo] with a unique,
    session-scoped URI for each acquisition — the counter is only advanced
    at that point, not at construction time.

    The URI produced by
    [`next_storage_info`][redsun_mimir.presenter.storage.FileStoragePresenter.next_storage_info]
    follows the structure::

        file:///<base_dir>/<session>/<YYYY_MM_DD>/<plan_name>_<counter>

    Parameters
    ----------
    name : str
        Identity key of the presenter.
    devices : Mapping[str, Device]
        Mapping of device names to device instances (unused; required by
        the [`Presenter`][redsun.presenter.Presenter] base class).
    base_dir : str | None, optional
        Absolute root directory for all output files.
        Defaults to ``~/redsun-storage``

    Attributes
    ----------
    sigStorageInfoChanged : Signal[StorageInfo]
        Emitted when the active base directory or session changes.
        Carries the updated [`StorageInfo`][redsun.storage.StorageInfo] so that
        other presenters can refresh their cached reference.
    """

    sigStorageInfoChanged = Signal(StorageInfo)

    def __init__(
        self,
        name: str,
        devices: Mapping[str, Device],
        /,
        base_dir: str | None = None,
    ) -> None:
        super().__init__(name, devices)
        if base_dir is not None:
            _base_dir = Path(base_dir)
        else:
            _base_dir = Path.home() / "redsun-storage"
        self._provider = SessionPathProvider(base_dir=_base_dir)
        self._storage_info = StorageInfo(uri=str(self._provider.base_dir))
        self.logger.info(f"Initialized with base dir: {self._provider.base_dir}")

    @property
    def storage_info(self) -> StorageInfo:
        """The current base-URI storage info held by the container."""
        return self._storage_info

    def next_storage_info(self, plan_name: str) -> StorageInfo:
        """Return a fresh [`StorageInfo`][redsun.storage.StorageInfo] for one acquisition.

        Calls the internal [`SessionPathProvider`][redsun.storage.SessionPathProvider]
        with *plan_name* to advance that plan's counter and lock in a
        unique URI.  Returns a new [`StorageInfo`][redsun.storage.StorageInfo]
        with an empty ``devices`` dict — motors, lights, and detectors
        will populate it during their ``prepare()`` calls.

        This method should be called by the plan body exactly once per
        acquisition event (e.g. when the stream action fires).

        Parameters
        ----------
        plan_name :
            Name of the plan being executed (e.g. ``"live_stream"``,
            ``"snap"``).  Each plan name has an independent counter.

        Returns
        -------
        StorageInfo
            Fresh instance with a unique URI and empty devices dict.
        """
        uri = self._provider(plan_name).store_uri
        return StorageInfo(uri=uri)

    def update_base_dir(self, base_dir: Path) -> None:
        """Replace the output base directory.

        Updates the [`SessionPathProvider`][redsun.storage.SessionPathProvider] base
        directory (which rescans for existing directories), refreshes
        the container's [`StorageInfo`][redsun.storage.StorageInfo], and emits
        [`sigStorageInfoChanged`][redsun_mimir.presenter.storage.FileStoragePresenter.sigStorageInfoChanged].

        Called when the user selects a new output directory from the view.

        Parameters
        ----------
        base_dir :
            New root output directory.
        """
        self._provider.base_dir = base_dir
        self._storage_info = StorageInfo(uri=base_dir.as_posix())
        self._container.storage_info = self._storage_info
        self.sigStorageInfoChanged.emit(self._storage_info)
        self.logger.info(f"Storage base dir updated to: {base_dir}")

    def update_session(self, session: str) -> None:
        """Update the session name used in the output path.

        Updates the [`SessionPathProvider`][redsun.storage.SessionPathProvider] session
        (which rescans the new session directory), refreshes the container's
        [`StorageInfo`][redsun.storage.StorageInfo], and emits
        [`sigStorageInfoChanged`][redsun_mimir.presenter.storage.FileStoragePresenter.sigStorageInfoChanged].

        Parameters
        ----------
        session : str
            New session name (e.g. ``"experiment_01"``).
        """
        self._provider.session = session
        self._storage_info = StorageInfo(uri=self._provider.base_dir.as_posix())
        self._container.storage_info = self._storage_info
        self.sigStorageInfoChanged.emit(self._storage_info)
        self.logger.info(f"Storage session updated to: {session}")

    def register_providers(self, container: VirtualContainer) -> None:
        """Push the initial StorageInfo to the container and register signals."""
        self._container = container
        container.storage_info = self._storage_info
        container.register_signals(self)

    def inject_dependencies(self, container: VirtualContainer) -> None:
        """Connect to path-change and session-change requests from the view."""
        sigs = find_signals(
            container,
            ["sigBaseDirChangeRequest", "sigSessionChangeRequest"],
        )
        if "sigBaseDirChangeRequest" in sigs:
            sigs["sigBaseDirChangeRequest"].connect(self.update_base_dir)
        if "sigSessionChangeRequest" in sigs:
            sigs["sigSessionChangeRequest"].connect(self.update_session)
