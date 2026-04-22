from __future__ import annotations

from typing import TYPE_CHECKING, Any

from bluesky.protocols import Descriptor  # noqa: TC002
from dependency_injector import providers
from event_model import DocumentRouter
from redsun.aio import run_coro
from redsun.log import Loggable
from redsun.presenter import Presenter
from redsun.utils import find_signals
from redsun.virtual import Signal

from redsun_mimir.protocols import DetectorProtocol  # noqa: TC001

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bluesky.protocols import Reading
    from event_model import Event
    from ophyd_async.core import Device, SignalRW
    from redsun.virtual import VirtualContainer


class DetectorPresenter(Presenter, DocumentRouter, Loggable):
    """Presenter for detector configuration and live data routing.

    Implements [`DocumentRouter`][event_model.DocumentRouter] to receive
    event documents emitted by the run engine and forward new image data
    to [`DetectorView`][redsun_mimir.view.DetectorView] via the virtual container.

    Parameters
    ----------
    name :
        Identity key of the presenter.
    devices :
        Mapping of device names to device instances.
    timeout : float | None, keyword-only, optional
        Timeout in seconds for async configuration calls.
        Defaults to ``1.0``.
    hints : list[str] | None, keyword-only, optional
        List of data key suffixes to look for in event documents
        when routing data to the view.
        Defaults to ``["buffer", "roi"]``.

    Attributes
    ----------
    sigNewConfiguration :
        Emitted after a detector setting is successfully applied.
        Carries the detector name (``str``) and a mapping of the
        changed setting to its new value (``dict[str, object]``).
    sigNewData :
        Emitted on each incoming event document.
        Carries a nested ``dict`` keyed by detector name.
    """

    sigNewConfiguration = Signal(str, str, object)
    sigNewData = Signal(object)

    def __init__(
        self,
        name: str,
        devices: Mapping[str, Device],
        /,
        timeout: float | None = 1.0,
        hints: list[str] | None = None,
    ) -> None:
        super().__init__(name, devices)
        self.timeout = timeout or 1.0
        self.hints = hints or ["buffer", "roi"]
        self.detectors: dict[str, DetectorProtocol] = {
            name: device
            for name, device in devices.items()
            if isinstance(device, DetectorProtocol)
        }
        self.current_stream = ""
        self.packet: dict[str, dict[str, Any]] = {}

    def register_providers(self, container: VirtualContainer) -> None:
        """Register detector info as providers in the DI container.

        Also registers detector signals in the container.
        """
        container.detector_descriptors = providers.Object(self.devices_description())
        container.detector_readings = providers.Object(self.devices_configuration())
        container.register_signals(self)
        container.register_callbacks(self)

    def inject_dependencies(self, container: VirtualContainer) -> None:
        """Connect to the virtual container signals."""
        sigs = find_signals(container, ["sigPropertyChanged"])
        if "sigPropertyChanged" in sigs:
            sigs["sigPropertyChanged"].connect(self.configure)

    def devices_configuration(self) -> dict[str, Reading[Any]]:
        """Get the current configuration readings of all detector devices."""
        result: dict[str, Reading[Any]] = {}
        for device in self.detectors.values():
            result.update(run_coro(device.read_configuration()))
        return result

    def devices_description(self) -> dict[str, Descriptor]:
        """Get the configuration descriptors of all detector devices."""
        result: dict[str, Descriptor] = {}
        for device in self.detectors.values():
            result.update(run_coro(device.describe_configuration()))
        return result

    def configure(self, detector: str, property: str, value: Any) -> None:
        """Configure a detector property based on a user request from the view.

        Parameters
        ----------
        detector : str
            Bare device name as emitted by the view.
        property : str
            Configuration key representing the setting to change.
        value : object
            New value for the setting.
        """
        match property:
            case "roi":
                roi = self.detectors[detector].roi
                run_coro(self._set(detector, roi, value))
            case "exposure":
                exposure = self.detectors[detector].exposure
                run_coro(self._set(detector, exposure, value))
            case "pixel_dtype":
                pixel_dtype = self.detectors[detector].pixel_dtype
                run_coro(self._set(detector, pixel_dtype, value))
            case _:
                self.logger.error(
                    f"Unknown property {property!r} for detector {detector!r}"
                )

    async def _set(self, det_name: str, obj: SignalRW[Any], value: Any) -> None:
        """Set *obj* to *value* asynchronously."""
        status = obj.set(value)
        await status
        if not status.success:
            self.logger.error(f"Failed to set {obj} to {value!r}: {status.exception()}")
        else:
            new_reading = await obj.read()
            value = new_reading[obj.name]["value"]
            self.sigNewConfiguration.emit(det_name, obj.name, value)

    def event(self, doc: Event) -> Event:
        """Process new event documents and route data to the view."""
        for key, value in doc["data"].items():
            parts = key.split("-")
            if len(parts) < 2:
                continue
            obj_name, hint = parts[0], parts[1]
            if hint in self.hints:
                self.packet.setdefault(obj_name, {})
                self.packet[obj_name][hint] = value
        self.sigNewData.emit(self.packet)
        return doc
