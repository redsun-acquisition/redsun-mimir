from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from dependency_injector import providers
from event_model import DocumentRouter
from redsun.engine import get_shared_loop
from redsun.log import Loggable
from redsun.presenter import Presenter
from redsun.storage import SessionPathProvider, handle_descriptor_metadata
from redsun.storage.presenter import get_available_writers
from redsun.utils import find_signals

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    from event_model.documents import EventDescriptor
    from redsun.device import Device
    from redsun.virtual import VirtualContainer


class FileStoragePresenter(Presenter, DocumentRouter, Loggable):
    """Presenter responsible for wiring writer URIs before each acquisition.

    Before each plan launch, iterates all registered writers and calls
    ``writer.set_uri()`` using the path provider stored on the container.
    The URI is generated as::

        provider(plan_name, group=writer_name).store_uri

    which produces paths of the form::

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
        self._path_provider = SessionPathProvider(
            base_dir=root_directory, session="default"
        )

        self.available_writers = get_available_writers(devices)

    def register_providers(self, container: VirtualContainer) -> None:
        """Provide the root directory and a string view of the available writers."""
        self._path_provider.session = container.session
        container.root_directory = providers.Object(str(self._path_provider.base_dir))

        # extract the available writers by mimetype and group
        available_writers_map: dict[str, list[str]] = {}
        for mimetype, groups in self.available_writers.items():
            available_writers_map[mimetype] = list(groups.keys())

        container.available_writers = providers.Object(available_writers_map)
        container.register_callbacks(self)

    def inject_dependencies(self, container: VirtualContainer) -> None:
        """Connect pre-launch, root-change, and plan-done signals."""
        sigs = find_signals(
            container,
            ["sigPreLaunchNotify", "sigRootDirChanged", "sigPlanDone"],
        )
        if "sigPreLaunchNotify" in sigs:
            sigs["sigPreLaunchNotify"].connect(self._prepare_writers)
        if "sigRootDirChanged" in sigs:
            sigs["sigRootDirChanged"].connect(self._refresh_path_provider)
        if "sigPlanDone" in sigs:
            sigs["sigPlanDone"].connect(self._close_writers)

    def descriptor(self, doc: EventDescriptor) -> EventDescriptor | None:
        """Forward device configuration metadata into active writers."""
        handle_descriptor_metadata(doc, self._devices)
        return doc

    def _prepare_writers(self, plan_name: str) -> None:
        """Set a fresh URI on every registered writer before the plan starts.

        Also clears the writer source cache so the previous run's sources
        do not bleed into the new run.

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
                path_info = self._path_provider(plan_name, group_name)
                writer.clear_sources()
                writer.set_uri(path_info.store_uri)
                self.logger.debug(
                    f"Set URI for writer ({group_name!r}, {mimetype!r}): "
                    f"{path_info.store_uri}"
                )

    def _close_writers(self) -> None:
        """Close all registered writers after the plan completes."""
        if not self.available_writers:
            return
        loop = get_shared_loop()
        for groups in self.available_writers.values():
            for writer in groups.values():
                try:
                    future = asyncio.run_coroutine_threadsafe(writer.close(), loop)
                    future.result(timeout=10.0)
                except Exception:  # noqa: PERF203
                    self.logger.exception("Error closing writer %r.", writer)

    def _refresh_path_provider(self, new_base_dir: str) -> None:
        """Update the base directory of the path provider when it changes.

        Parameters
        ----------
        new_base_dir : str
            The new base directory to set on the path provider.
        """
        self._path_provider.base_dir = Path(new_base_dir)
