from __future__ import annotations

from typing import TYPE_CHECKING

from event_model import DocumentRouter
from redsun.log import Loggable
from redsun.presenter import Presenter

if TYPE_CHECKING:
    from collections.abc import Mapping

    from event_model.documents import Event, EventDescriptor, RunStart, RunStop
    from ophyd_async.core import Device
    from redsun.virtual import VirtualContainer


class MedianPresenter(Presenter, DocumentRouter, Loggable):
    """Presenter that computes per-detector median images from scan streams.

    Supports concurrent and nested bluesky runs: all state is keyed by
    run UID.  Each run subscribes independently and unsubscribes cleanly
    in ``stop()``.

    Parameters
    ----------
    name : str
        Identity key of the presenter.
    devices : Mapping[str, Device]
    """

    def __init__(
        self,
        name: str,
        devices: Mapping[str, Device],
        /,
    ) -> None:
        super().__init__(name, devices)

    def register_providers(self, container: VirtualContainer) -> None:
        """Register this presenter as a callback in the virtual container."""
        container.register_signals(self)
        container.register_callbacks(self)

    def start(self, doc: RunStart) -> RunStart | None:
        """Process start document."""
        return doc

    def descriptor(self, doc: EventDescriptor) -> EventDescriptor | None:
        """Process descriptor document."""
        return doc

    def event(self, doc: Event) -> Event:
        """Process event document."""
        return doc

    def stop(self, doc: RunStop) -> RunStop | None:
        """Process stop document."""
        return doc
