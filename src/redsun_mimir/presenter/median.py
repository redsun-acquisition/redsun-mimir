from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from event_model import DocumentRouter
from redsun.device import ControllableDataWriter
from redsun.log import Loggable
from redsun.presenter import Presenter
from redsun.storage import HasWriterLogic
from redsun.utils.descriptors import parse_key
from redsun.virtual import Signal

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    import numpy.typing as npt
    from event_model.documents import Event, EventDescriptor, RunStart, RunStop
    from redsun.device import Device
    from redsun.virtual import VirtualContainer


class MedianPresenter(Presenter, DocumentRouter, Loggable):
    """Presenter that computes per-detector median images from scan streams.

    Implements [`DocumentRouter`][event_model.DocumentRouter] to receive
    event documents. Frames arriving on expected streams (e.g. ``square_scan``)
    are stacked; at the end of the run the median across the stack is computed,
    written to the detector's ``writer_logic``, and stored for optional live
    correction forwarded to [`DetectorView`][redsun_mimir.view.DetectorView].

    Parameters
    ----------
    name :
        Identity key of the presenter.
    devices :
        Mapping of device names to device instances.
    live_streams: list[str] | None, keyword-only, optional
        Stream names to look for when applying median correction to live data.
        If ``None``, no live data will be processed.
    median_streams: list[str] | None, keyword-only, optional
        Stream names to look for when accumulating raw frames for median
        computation. If ``None``, no scan data will be processed.
    hints: list[str] | None, keyword-only, optional
        Data key suffixes to extract from event documents (e.g. ``["buffer"]``).
        If ``None``, no data will be processed.

    Attributes
    ----------
    sigNewData: Signal[dict[str, dict[str, numpy.ndarray]]]
        Emitted with median-corrected image data.
        Carries the object name suffixed with ``"_median"``
        (e.g. ``"camera1_median"``).
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
        self._devices = devices
        self.median_streams = frozenset(median_streams or [])
        self.live_streams = frozenset(live_streams or [])
        self.hints = frozenset(hints or [])

        # Accumulated raw frames: (obj_name, hint) -> list of arrays
        self._frames: dict[tuple[str, str], list[npt.NDArray[Any]]] = {}
        # Computed medians for live correction: obj_name -> hint -> array
        self.medians: dict[str, dict[str, npt.NDArray[Any]]] = {}
        self.packet: dict[str, dict[str, npt.NDArray[Any]]] = {}
        self.uid_to_stream: dict[str, str] = {}

        active = (
            len(self.median_streams) > 0 and len(self.live_streams) > 0 and self.hints
        )

        if active:
            scan_streams_msg = ", ".join(self.median_streams)
            live_streams_msg = ", ".join(self.live_streams)
            hints_msg = ", ".join(self.hints)
            self.logger.info(
                f"Initialized: scan streams '{scan_streams_msg}', "
                f"live streams '{live_streams_msg}', "
                f"hints '{hints_msg}'"
            )
        else:
            if self.median_streams or self.live_streams:
                self.logger.warning(
                    "Initialized: no hints declared; presenter will be inactive"
                )
            elif self.hints:
                self.logger.warning(
                    "Initialized: no streams declared; presenter will be inactive"
                )
            else:
                self.logger.warning(
                    "Initialized: with no streams or hints declared; presenter will be inactive"
                )

    def register_providers(self, container: VirtualContainer) -> None:
        """Register this presenter as a callback in the virtual container."""
        container.register_signals(self)
        container.register_callbacks(self)

    def start(self, doc: RunStart) -> RunStart | None:
        """Process a new start document — clear the local caches."""
        self._frames.clear()
        self.medians.clear()
        self.packet.clear()
        return doc

    def descriptor(self, doc: EventDescriptor) -> EventDescriptor | None:
        """Store the stream name keyed by descriptor UID."""
        self.uid_to_stream.setdefault(doc["uid"], doc["name"])
        return doc

    def event(self, doc: Event) -> Event:
        """Process new event documents.

        Frames from ``median_streams`` are accumulated for later median
        computation. Frames from ``live_streams`` receive median correction.
        """
        if not (self.median_streams and self.live_streams and self.hints):
            return doc

        stream_name = self.uid_to_stream[doc["descriptor"]]
        if stream_name in self.median_streams:
            doc = self._accumulate_frame(doc)
        elif stream_name in self.live_streams:
            doc = self._apply_median(doc)
        return doc

    def stop(self, doc: RunStop) -> RunStop | None:
        """Compute and write medians at the end of the run.

        For each accumulated (device, hint) pair the median is computed across
        all stacked frames, stored for live correction, and written to the
        device's ``writer_logic`` under the key ``{device_name}_median``.
        """
        if not self._frames:
            return doc

        # Group by obj_name so we write once per detector
        medians_by_device: dict[str, dict[str, npt.NDArray[Any]]] = {}
        for (obj_name, hint), frames in self._frames.items():
            if not frames:
                continue
            stack = np.stack(frames, axis=0)
            median_frame = np.median(stack, axis=0).astype(stack.dtype)
            medians_by_device.setdefault(obj_name, {})[hint] = median_frame
            # Store for subsequent live correction via _apply_median
            self.medians.setdefault(obj_name, {})[hint] = median_frame

        for obj_name, hint_medians in medians_by_device.items():
            device = self._devices.get(obj_name)
            if not isinstance(device, HasWriterLogic) or not isinstance(
                device.writer_logic, ControllableDataWriter
            ):
                continue
            # Write one median frame per device; use the first (and typically only) hint
            for hint, median_frame in hint_medians.items():
                median_key = f"{obj_name}_median"
                try:
                    device.writer_logic.register(
                        name=median_key,
                        dtype=median_frame.dtype,
                        shape=median_frame.shape,
                        capacity=1,
                    )
                    device.writer_logic.open(median_key)
                    device.writer_logic.write_frame(median_key, median_frame)
                    self.logger.debug(
                        "Wrote median for %s hint '%s' to key '%s'.",
                        obj_name,
                        hint,
                        median_key,
                    )
                except Exception:
                    self.logger.exception(
                        "Failed to write median for %s hint '%s'.", obj_name, hint
                    )
                break  # one write per detector (first matching hint)

        self._frames.clear()
        return doc

    def _apply_median(self, doc: Event) -> Event:
        if not self.medians:
            return doc
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
        if self.packet:
            self.sigNewData.emit(self.packet)
        return doc

    def _accumulate_frame(self, doc: Event) -> Event:
        """Append raw frames from a scan event to the accumulation buffer."""
        for key, value in doc["data"].items():
            try:
                obj_name, hint = parse_key(key)
            except ValueError:
                continue
            if hint not in self.hints:
                continue
            self._frames.setdefault((obj_name, hint), []).append(np.asarray(value))
        return doc
