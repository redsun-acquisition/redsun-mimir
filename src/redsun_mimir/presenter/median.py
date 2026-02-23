from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from event_model import DocumentRouter
from event_model.documents.event_descriptor import EventDescriptor
from redsun.log import Loggable
from redsun.presenter import Presenter
from redsun.utils.descriptors import parse_key
from redsun.virtual import Signal

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    import numpy.typing as npt
    from event_model.documents import Event, EventDescriptor, RunStart
    from redsun.device import Device
    from redsun.virtual import VirtualContainer


class MedianPresenter(Presenter, DocumentRouter, Loggable):
    """Presenter that computes per-detector median images from scan streams.

    Implements [`DocumentRouter`][event_model.DocumentRouter] to receive
    event documents. Frames arriving on expected streams (e.g. `square_scan`)
    are stacked; on the next live-stream event the median across the stack is
    computed and applied to the incoming buffer before forwarding it to
    [`DetectorView`][redsun_mimir.view.DetectorView].

    Parameters
    ----------
    name :
        Identity key of the presenter.
    devices :
        Mapping of device names to device instances. Unused by this presenter.
    live_streams: list[str] | None, keyword-only, optional
        List of stream names to look for in event descriptors when
        applying the median correction using pre-computed medians. If `None`, no live data will be processed.
    median_streams: list[str] | None, keyword-only, optional
        List of stream names to look for in event descriptors when directly
        computing the median from scan data, or displaying pre-computed median
        data from a MedianPseudoDevice. If `None`, no scan data will be processed.
    hints: list[str] | None, keyword-only, optional
        List of data key suffixes to look for in event documents when applying
        the median correction. If `None`, no data will be processed. Defaults to `None`.

    Attributes
    ----------
    sigNewData: Signal[dict[str, dict[str, numpy.ndarray]]]
        Emitted with median-corrected image data.
        Carries the object name corrected with the suffix "median"
        for distinguishing from the original data, i.e. "camera-median"

    Notes
    -----
    The presenter expects both `streams` and `hints` to be configured.
    If either is missing, the presenter will be inactive.
    """

    sigNewData = Signal(object)

    def __init__(
        self,
        name: str,
        devices: Mapping[str, Device],
        /,
        live_streams: list[str] | None = None,
        median_streams: list[str] | None = None,
        hints: list[str] | None = None,
    ) -> None:
        super().__init__(name, devices)
        self.median_streams = frozenset(median_streams or [])
        self.live_streams = frozenset(live_streams or [])
        self.hints = frozenset(hints or [])
        self.median_stacks: dict[str, dict[str, list[npt.NDArray[Any]]]] = {}
        self.medians: dict[str, dict[str, npt.NDArray[Any]]] = {}
        self.packet: dict[str, dict[str, npt.NDArray[Any]]] = {}
        self.uid_to_stream: dict[str, str] = {}
        self.previous_stream: str = ""

        active = (self.median_streams or self.live_streams) and self.hints

        if active:
            self.logger.info(
                f"Initialized: scan streams {', '.join(self.median_streams)}, "
                f"live streams {', '.join(self.live_streams)}, "
                f"hints {', '.join(self.hints)}"
            )
        else:
            if self.median_streams or self.live_streams:
                self.logger.warning(
                    "Initialized: no hints detected; presenter will be inactive"
                )
            elif self.hints:
                self.logger.warning(
                    "Initialized: no active streams detected; presenter will be inactive"
                )
            else:
                self.logger.warning(
                    "Initialized: with no active streams hints detected; presenter will be inactive"
                )

    def register_providers(self, container: VirtualContainer) -> None:
        """Register this presenter as a callback in the virtual container."""
        container.register_signals(self)
        container.register_callbacks(self)

    def start(self, doc: RunStart) -> RunStart | None:
        """Process a new start document.

        Clear the local cache.
        """
        self.median_stacks.clear()
        self.medians.clear()
        self.packet.clear()
        self.previous_stream = ""
        return doc

    def descriptor(self, doc: EventDescriptor) -> EventDescriptor | None:
        """Process new descriptor documents.

        Store the stream name and its UID to identify incoming events
        future incoming events.

        Parameters
        ----------
        doc : ``EventDescriptor``
            Descriptor document.

        Returns
        -------
        doc : ``EventDescriptor | None``
            Unmodified descriptor document.
        """
        self.uid_to_stream.setdefault(doc["uid"], doc["name"])
        return doc

    def event(self, doc: Event) -> Event:
        """Process new event documents.

        Parameters
        ----------
        doc : ``Event``
            Event document.

        Returns
        -------
        doc : ``Event``
            Processed event document with median calculated.
        """
        if not (self.median_streams and self.live_streams and self.hints):
            return doc

        stream_name = self.uid_to_stream[doc["descriptor"]]
        if stream_name in self.median_streams:
            if self.previous_stream != stream_name:
                self.median_stacks.clear()
                self.medians.clear()
                self.previous_stream = stream_name
            if any(key.endswith("_median") for key in doc["data"]):
                doc = self._store_precomputed(doc)
            else:
                doc = self._prepare_scan_data(doc)
        elif stream_name in self.live_streams:
            if self.median_stacks and not self.medians:
                self.medians = {
                    obj_name: {
                        data_key: np.median(np.stack(data_values, axis=0), axis=0)
                        for data_key, data_values in data_dict.items()
                    }
                    for obj_name, data_dict in self.median_stacks.items()
                }
            doc = self._apply_median(doc)
        return doc

    def _prepare_scan_data(self, doc: Event) -> Event:
        for key, value in doc["data"].items():
            try:
                obj_name, hint = parse_key(key)
            except ValueError:
                continue
            if hint in self.hints:
                self.median_stacks.setdefault(obj_name, {})
                self.median_stacks[obj_name].setdefault(hint, [])
                self.median_stacks[obj_name][hint].append(value)
        return doc

    def _apply_median(self, doc: Event) -> Event:
        if self.median_stacks:
            self.packet.clear()
            for key, value in doc["data"].items():
                try:
                    obj_name, hint = parse_key(key)
                except ValueError:
                    continue
                if hint not in self.hints:
                    continue
                if obj_name not in self.medians or hint not in self.medians[obj_name]:
                    continue
                median_applied: npt.NDArray[Any] = value / self.medians[obj_name][hint]
                suffixed = f"{obj_name}_median"
                self.packet.setdefault(suffixed, {})
                self.packet[suffixed][hint] = median_applied
            if len(self.packet) > 0:
                self.sigNewData.emit(self.packet)
        return doc

    def _store_precomputed(self, doc: Event) -> Event:
        for key, value in doc["data"].items():
            try:
                obj_name, hint = parse_key(key)
            except ValueError:
                continue
            if hint not in self.hints:
                continue
            # strip the _median suffix to match the obj_name used in _apply_median
            base_name = obj_name.removesuffix("_median")
            self.medians.setdefault(base_name, {})
            self.medians[base_name][hint] = np.asarray(value)
        return doc
