from __future__ import annotations

from typing import TYPE_CHECKING

from event_model import DocumentRouter
from redsun.aio import run_coro
from redsun.log import Loggable
from redsun.presenter import Presenter
from redsun.virtual import Signal

from redsun_mimir.protocols import MedianFlyer

if TYPE_CHECKING:
    from collections.abc import Mapping

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

    sigNewMedian = Signal(object)  # dict[str, Reading[Any]]

    def __init__(
        self,
        name: str,
        devices: Mapping[str, Device],
        /,
    ) -> None:
        super().__init__(name, devices)
        self.medians: dict[str, MedianFlyer] = {
            name: device
            for name, device in devices.items()
            if isinstance(device, MedianFlyer)
        }

        # the internals of a signal backend are invoked in
        # a running event loop; we need to dispatch the
        # subscription coroutine to the background thread
        async def subscribe_to_buffers() -> None:
            for dev in self.medians.values():
                dev.median.buffer.subscribe_reading(self.sigNewMedian.emit)

        run_coro(subscribe_to_buffers())

    def register_providers(self, container: VirtualContainer) -> None:
        """Register this presenter as a callback in the virtual container."""
        container.register_signals(self)
        container.register_callbacks(self)
