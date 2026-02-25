from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from dependency_injector import providers
from redsun.log import Loggable
from redsun.presenter import Presenter
from redsun.storage import SessionPathProvider
from redsun.storage.presenter import get_available_writers

from redsun_mimir.utils import find_signals

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    from redsun.device import Device
    from redsun.virtual import VirtualContainer


class FileStoragePresenter(Presenter, Loggable):
    """Presenter responsible for wiring writer URIs before each acquisition.

    Before each plan launch, iterates all registered writers and calls
    ``writer.set_uri()`` using the path provider stored on the container.
    The URI is generated as::

        provider(plan_name, group=writer_name).store_uri

    which produces paths of the form::

        <base_dir>/<session>/<date>/<plan_name>_<group>_<counter>

    This presenter must be registered *before* ``AcquisitionPresenter``
    in the application container so that URIs are set before the plan
    starts executing.

    Parameters
    ----------
    name : str
        Identity key of the presenter.
    devices : Mapping[str, Device]
        Available devices (unused, required by ``Presenter`` interface).
    """

    def __init__(
        self,
        name: str,
        devices: Mapping[str, Device],
        /,
        **kwargs: Any,
    ) -> None:
        super().__init__(name, devices, **kwargs)
        root_directory = Path.home() / "redsun-storage"
        self._path_provider = SessionPathProvider(
            base_dir=root_directory, session="default"
        )

        self.available_writers = get_available_writers()

    def register_providers(self, container: VirtualContainer) -> None:
        """Provide the root directory and a string view of the available writers."""
        self._path_provider.session = container.session
        container.root_directory = providers.Object(str(self._path_provider.base_dir))

        # extract the available writers by mimetype and group
        available_writers_map: dict[str, list[str]] = {}
        for mimetype, groups in self.available_writers.items():
            available_writers_map[mimetype] = list(groups.keys())

        container.available_writers = providers.Object(available_writers_map)

    def inject_dependencies(self, container: VirtualContainer) -> None:
        """Connect pre-launch and root change signals."""
        sigs = find_signals(container, ["sigPreLaunchPlanRequest", "sigRootDirChanged"])
        if "sigPreLaunchPlanRequest" in sigs:
            sigs["sigPreLaunchPlanRequest"].connect(self._set_writer_uris)
        if "sigRootDirChanged" in sigs:
            sigs["sigRootDirChanged"].connect(self._refresh_path_provider)

    def _set_writer_uris(self, plan_name: str) -> None:
        """Set a fresh URI on every registered writer before the plan starts.

        Parameters
        ----------
        plan_name : str
            Name of the plan about to be launched.
        """
        if not self.available_writers:
            self.logger.debug("No writers registered; skipping URI assignment.")
            return

        for mimetype, groups in self.available_writers.items():
            for group_name, writer in groups.items():
                key = f"{plan_name}_{group_name}"
                path_info = self._path_provider(key)
                writer.set_uri(path_info.store_uri)
                self.logger.debug(
                    f"Set URI for writer ({group_name!r}, {mimetype!r}): "
                    f"{path_info.store_uri}"
                )

    def _refresh_path_provider(self, new_base_dir: str) -> None:
        """Update the base directory of the path provider when it changes.

        Parameters
        ----------
        new_base_dir : str
            The new base directory to set on the path provider.
        """
        self._path_provider.base_dir = Path(new_base_dir)
