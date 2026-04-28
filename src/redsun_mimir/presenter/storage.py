from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from dependency_injector import providers
from event_model import DocumentRouter
from redsun.log import Loggable
from redsun.presenter import Presenter
from redsun.utils import find_signals

from redsun_mimir.storage import SessionPathProvider

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    from ophyd_async.core import Device
    from redsun.virtual import VirtualContainer


class FileStoragePresenter(Presenter, DocumentRouter, Loggable):
    """Presenter responsible for wiring writer paths before each acquisition.

    Before each plan launch, iterates all registered writers and calls
    ``writer.set_store_path()`` using the path provider stored on the container.
    The path is generated as::

        <base_dir>/<session>/<date>/<plan_name>_<group>_<counter>

    Also registers as a bluesky callback to forward descriptor metadata
    (device configuration) into the active writers via
    :func:`~redsun.storage.handle_descriptor_metadata`, and closes all
    writers when ``sigPlanDone`` is emitted.

    Parameters
    ----------
    name : str
        Identity key of the presenter.
    devices : Mapping[str, Device]
        Available devices. Used to discover writers via
        :func:`~redsun.storage.presenter.get_available_writers`.
    """

    def __init__(
        self,
        name: str,
        devices: Mapping[str, Device],
        /,
        **kwargs: Any,
    ) -> None:
        super().__init__(name, devices, **kwargs)
        self._devices = devices
        root_directory = Path.home() / "redsun-storage"
        self._path_provider = SessionPathProvider(base_dir=root_directory, session="")

    def register_providers(self, container: VirtualContainer) -> None:
        """Provide the path provider and expose its signals on the container."""
        self._path_provider.session = container.session
        container.root_directory = providers.Object(str(self._path_provider.base_dir))
        container.path_provider = providers.Object(self._path_provider)
        container.register_callbacks(self)

    def inject_dependencies(self, container: VirtualContainer) -> None:
        """Connect pre-launch, root-change, and plan-done signals."""
        sigs = find_signals(
            container,
            ["sigPreLaunchNotify", "sigPlanDone"],
        )
        if "sigPreLaunchNotify" in sigs:
            sigs["sigPreLaunchNotify"].connect(self._prepare_writers)
        if "sigPlanDone" in sigs:
            sigs["sigPlanDone"].connect(self._close_writers)

    def _prepare_writers(self, plan_name: str) -> None:
        """Set a fresh store path on every registered writer before the plan starts.

        Parameters
        ----------
        plan_name : str
            Name of the plan about to be launched.
        """
        self._path_provider.group = plan_name

    def _close_writers(self) -> None:
        """Reset the group name after the plan completes."""
        self._path_provider.group = None
