from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Literal

import numpy as np
from event_model import DocumentRouter
from ophyd_async.core import SignalR
from redsun.log import Loggable
from redsun.presenter import Presenter
from redsun.storage import DataWriter, SourceInfo
from redsun.virtual import Signal

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from typing import Any

    import numpy.typing as npt
    from bluesky.protocols import Reading
    from event_model.documents import Event, EventDescriptor, RunStart, RunStop
    from ophyd_async.core import Device
    from redsun.virtual import VirtualContainer


class MedianPresenter(Presenter, DocumentRouter, Loggable):
    """Presenter that computes per-detector median images from scan streams.

    Subscribes directly to each detector's ``buffer``
    [`SignalR`][ophyd_async.core.SignalR].  Frames arriving while the run is
    in the ``median_streams`` phase are accumulated.  When a descriptor for a
    ``live_streams`` stream arrives after a scan phase (stream switch), the
    median is computed asynchronously, written to the detector's
    ``writer``, and stored for live correction forwarded to
    [`DetectorView`][redsun_mimir.view.DetectorView].

    Supports concurrent and nested bluesky runs: all state is keyed by
    run UID.  Each run subscribes independently and unsubscribes cleanly
    in ``stop()``.

    Parameters
    ----------
    name :
        Identity key of the presenter.
    devices :
        Mapping of device names to device instances.
    live_streams : list[str] | None, keyword-only, optional
        Stream names that carry live (corrected) data.
        If ``None``, no live data will be processed.
    median_streams : list[str] | None, keyword-only, optional
        Stream names to accumulate raw frames for median computation.
        If ``None``, no scan data will be processed.

    Attributes
    ----------
    sigNewData : Signal[dict[str, numpy.ndarray]]
        Emitted with median-corrected image data during live phases.
    """

    sigNewData = Signal(object)

    def __init__(
        self,
        name: str,
        devices: Mapping[str, Device],
        /,
        live_streams: list[str] | None = None,
        median_streams: list[str] | None = None,
    ) -> None:
        super().__init__(name, devices)
        self._devices = devices
        self.median_streams = frozenset(median_streams or [])
        self.live_streams = frozenset(live_streams or [])

        # All state keyed by run UID for multi-run safety
        self._phase: dict[str, Literal["idle", "scan", "live"]] = {}
        self._frames: dict[str, dict[str, list[npt.NDArray[Any]]]] = {}
        self._medians: dict[str, dict[str, npt.NDArray[Any]]] = {}
        self._subscriptions: dict[
            str, list[tuple[SignalR[Any], Callable[..., None]]]
        ] = {}
        self.uid_to_stream: dict[str, str] = {}

        active = len(self.median_streams) > 0 and len(self.live_streams) > 0
        if active:
            self.logger.info(
                f"Initialized: scan streams '{', '.join(self.median_streams)}', "
                f"live streams '{', '.join(self.live_streams)}'"
            )
        else:
            self.logger.warning(
                "Initialized: no streams declared; presenter will be inactive"
            )

    def register_providers(self, container: VirtualContainer) -> None:
        """Register this presenter as a callback in the virtual container."""
        container.register_signals(self)
        container.register_callbacks(self)

    def start(self, doc: RunStart) -> RunStart | None:
        """Subscribe to device buffers and initialise per-run state."""
        run_uid: str = doc["uid"]
        self._phase[run_uid] = "idle"
        self._frames[run_uid] = {}
        self._medians[run_uid] = {}

        subs: list[tuple[SignalR[Any], Callable[..., None]]] = []
        for device in self._devices.values():
            buf = getattr(device, "buffer", None)
            if buf is not None and isinstance(buf, SignalR):
                cb = partial(self._on_frame, run_uid=run_uid)
                buf.subscribe(cb)
                subs.append((buf, cb))
        self._subscriptions[run_uid] = subs
        return doc

    def descriptor(self, doc: EventDescriptor) -> EventDescriptor | None:
        """Track stream phase; dispatch median computation on stream switch."""
        run_uid: str = doc["run_start"]
        stream: str = doc["name"]
        self.uid_to_stream[doc["uid"]] = stream

        current = self._phase.get(run_uid, "idle")
        if stream in self.median_streams:
            self._phase[run_uid] = "scan"
        elif stream in self.live_streams:
            if current == "scan":
                self._compute_medians(run_uid)
            self._phase[run_uid] = "live"
        return doc

    def event(self, doc: Event) -> Event:
        """No-op — data arrives via buffer signal subscription."""
        return doc

    def stop(self, doc: RunStop) -> RunStop | None:
        """Unsubscribe from device buffers and clean up per-run state."""
        run_uid: str = doc["run_start"]
        for buf, cb in self._subscriptions.pop(run_uid, []):
            buf.clear_sub(cb)
        self._phase.pop(run_uid, None)
        self._frames.pop(run_uid, None)
        self._medians.pop(run_uid, None)
        return doc

    def _on_frame(
        self,
        reading: dict[str, Reading[npt.NDArray[Any]]],
        *,
        run_uid: str,
    ) -> None:
        """Route an incoming buffer reading based on the current run phase."""
        phase = self._phase.get(run_uid, "idle")
        if phase == "scan":
            for key, r in reading.items():
                self._frames[run_uid].setdefault(key, []).append(np.asarray(r["value"]))
        elif phase == "live":
            medians = self._medians.get(run_uid, {})
            if medians:
                self._emit_corrected(reading, medians)

    def _compute_medians(self, run_uid: str) -> None:
        """Compute per-key median from accumulated frames and write to storage."""
        frames_by_key = self._frames.get(run_uid, {})
        medians: dict[str, npt.NDArray[Any]] = {}

        # Build buffer-key → device lookup for writer access.
        buffer_to_device: dict[str, Device] = {}
        for device in self._devices.values():
            buf = getattr(device, "buffer", None)
            if buf is not None and isinstance(buf, SignalR) and buf.name:
                buffer_to_device[buf.name] = device

        for key, frames in frames_by_key.items():
            if not frames:
                continue
            stack = np.stack(frames, axis=0)
            median_frame: npt.NDArray[Any] = np.median(stack, axis=0).astype(
                stack.dtype
            )
            medians[key] = median_frame

            found_device = buffer_to_device.get(key)
            if found_device is None:
                continue
            writer = getattr(found_device, "writer", None)
            if not isinstance(writer, DataWriter):
                continue
            median_key = f"{found_device.name}_median"
            try:
                writer.register(
                    median_key,
                    SourceInfo(
                        dtype_numpy=np.dtype(median_frame.dtype).str,
                        shape=median_frame.shape,
                        capacity=1,
                    ),
                )
                writer.open()
                writer.write(median_key, median_frame)
                self.logger.debug(
                    "Wrote median for buffer key '%s' to storage key '%s'.",
                    key,
                    median_key,
                )
            except Exception:
                self.logger.exception(
                    "Failed to write median for buffer key '%s'.", key
                )

        self._medians[run_uid] = medians
        self._frames[run_uid] = {}  # drop raw frames

    def _emit_corrected(
        self,
        reading: dict[str, Reading[npt.NDArray[Any]]],
        medians: dict[str, npt.NDArray[Any]],
    ) -> None:
        """Divide live frames by the stored median and emit sigNewData."""
        packet: dict[str, npt.NDArray[Any]] = {}
        for key, r in reading.items():
            if key not in medians:
                continue
            corrected: npt.NDArray[Any] = np.asarray(r["value"]) / medians[key]
            packet[f"{key}_corrected"] = corrected
        if packet:
            self.sigNewData.emit(packet)
