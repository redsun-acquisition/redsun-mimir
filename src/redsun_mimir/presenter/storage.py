from __future__ import annotations

from typing import TYPE_CHECKING

from redsun.log import Loggable
from redsun.presenter import Presenter
from redsun.storage.presenter import get_available_writers

from redsun_mimir.utils import find_signals

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    from redsun.device import Device
    from redsun.storage import PathProvider
    from redsun.virtual import VirtualContainer


class StoragePresenter(Presenter, Loggable):
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
        super().__init__(name, devices)
        self._path_provider: PathProvider | None = None

    def register_providers(self, container: VirtualContainer) -> None:
        """No providers to register; signals are wired in inject_dependencies."""
        container.register_signals(self)

    def inject_dependencies(self, container: VirtualContainer) -> None:
        """Connect to the launch-plan signal and cache the path provider."""
        self._path_provider = getattr(container, "path_provider", None)
        if self._path_provider is None:
            self.logger.warning(
                "No path_provider found on container; "
                "writer URIs will not be set automatically."
            )

        sigs = find_signals(container, ["sigLaunchPlanRequest"])
        if "sigLaunchPlanRequest" in sigs:
            sigs["sigLaunchPlanRequest"].connect(self._set_writer_uris)

    def _set_writer_uris(self, plan_name: str, param_values: Mapping[str, Any]) -> None:
        """Set a fresh URI on every registered writer before the plan starts.

        Parameters
        ----------
        plan_name : str
            Name of the plan about to be launched.
        param_values : Mapping[str, Any]
            Plan parameter values (unused; forwarded by the signal).
        """
        if self._path_provider is None:
            return

        writers = get_available_writers()
        if not writers:
            self.logger.debug("No writers registered; skipping URI assignment.")
            return

        for mimetype, groups in writers.items():
            for group_name, writer in groups.items():
                path_info = self._path_provider(plan_name, group=group_name)
                writer.set_uri(path_info.store_uri)
                self.logger.debug(
                    f"Set URI for writer ({group_name!r}, {mimetype!r}): "
                    f"{path_info.store_uri}"
                )
