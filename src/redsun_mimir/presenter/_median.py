from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from event_model import DocumentRouter
from event_model.documents.event_descriptor import EventDescriptor
from sunflare.log import Loggable
from sunflare.presenter import PPresenter
from sunflare.virtual import Signal

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    import numpy.typing as npt
    from event_model.documents import Event, EventDescriptor, RunStart
    from sunflare.device import Device
    from sunflare.virtual import VirtualBus


class MedianPresenter(PPresenter, DocumentRouter, Loggable):
    """Presenter that calculates the median of incoming data.

    Stores incoming data from expected streams, computes the median
    when a non-expected stream event is received, and applies the median
    to the incoming data before emitting it to the viewer.

    Parameters
    ----------
    devices : ``Mapping[str, Device]``
        Mapping of device names to device instances.
        Unused in this presenter.
    virtual_bus : ``VirtualBus``
        Reference to the virtual bus.

    Attributes
    ----------
    sigNewData : ``Signal(dict[str, dict[str, Any]])``
        Signal emitting new data with median applied with structure:
        - outer key: object name with `[median]` suffix.
        - inner key: data key (e.g., `buffer`).
        - value: data array with median applied.
    """

    sigNewData = Signal(str, object)

    def __init__(
        self,
        devices: Mapping[str, Device],
        virtual_bus: VirtualBus,
        /,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        self.virtual_bus = virtual_bus

        # TODO: generalize this
        # via ctrl_info?
        self.expected_streams = frozenset(["square_scan"])
        self.hints = frozenset(["buffer"])
        self.median_stacks: dict[str, dict[str, list[npt.NDArray[Any]]]] = {}
        self.medians: dict[str, dict[str, npt.NDArray[Any]]] = {}
        self.packet: dict[str, dict[str, Any]] = {}
        self.uid_to_stream: dict[str, str] = {}
        self.previous_stream: str = ""

    def registration_phase(self) -> None:
        """Register the presenter on the virtual bus."""
        self.virtual_bus.register_signals(self)
        self.virtual_bus.register_callbacks(self)

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

        If the event descriptor UID corresponds to an expected stream,
        the data is stacked for median calculation. Otherwise,
        the median is calculated and emitted to the viewer.
        If no expected stream is found and the median has not been calculated yet,
        does nothing.

        Parameters
        ----------
        doc : ``Event``
            Event document.

        Returns
        -------
        doc : ``Event``
            Processed event document with median calculated.
        """
        stream_name = self.uid_to_stream[doc["descriptor"]]
        if stream_name in self.expected_streams:
            if self.previous_stream != stream_name:
                # clear the stack and the median
                # when a new stream is detected
                self.median_stacks.clear()
                self.medians.clear()
                self.previous_stream = stream_name
            doc = self._prepare_scan_data(doc)
        else:
            if self.median_stacks and not self.medians:
                # compute the median for each object and data key
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
        """Stash incoming scan data for median calculation."""
        for key, value in doc["data"].items():
            obj_name, data_key = key.split(":")
            if data_key in self.hints:
                self.median_stacks.setdefault(obj_name, {})
                self.median_stacks[obj_name].setdefault(data_key, [])
                self.median_stacks[obj_name][data_key].append(value)
        return doc

    def _apply_median(self, doc: Event) -> Event:
        """Apply the computed median to the incoming event data.

        Each object name is suffixed with '[median]' to indicate
        that the median has been applied. If the median has not been
        computed yet, the function returns the document unmodified.
        """
        if self.median_stacks:
            for key, value in doc["data"].items():
                obj_name, data_key = key.split(":")
                if data_key in self.hints:
                    median_applied: npt.NDArray[Any] = (
                        value / self.median_stacks[obj_name][data_key]
                    )
                    obj_name = f"{obj_name}[median]"
                    self.packet.setdefault(obj_name, {})
                    self.packet[obj_name][data_key] = median_applied
            self.sigNewData.emit(self.packet)
        return doc
