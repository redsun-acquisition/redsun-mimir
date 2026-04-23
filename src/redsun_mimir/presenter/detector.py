from __future__ import annotations

from typing import TYPE_CHECKING, Any

from bluesky.protocols import Descriptor  # noqa: TC002
from dependency_injector import providers
from redsun.aio import run_coro
from redsun.log import Loggable
from redsun.presenter import Presenter
from redsun.utils import find_signals
from redsun.virtual import Signal

from redsun_mimir.protocols import DetectorProtocol  # noqa: TC001

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bluesky.protocols import Reading
    from ophyd_async.core import Device, SignalRW
    from redsun.virtual import VirtualContainer

    from redsun_mimir.protocols import LayerSpec


class DetectorPresenter(Presenter, Loggable):
    """Presenter for detector configuration and live data routing.

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
    sigNewConfiguration : Signal[str, str, object]
        Emitted after a detector setting is successfully applied.
        Carries the detector name (``str``) and a mapping of the
        changed setting to its new value (``dict[str, object]``).
    sigNewData : Signal[dict[str, Reading[Any]]]
        Emitted when a new reading is available from a detector.
    """

    sigNewConfiguration = Signal(str, str, object)
    sigNewData = Signal(object)

    def __init__(
        self,
        name: str,
        devices: Mapping[str, Device],
        /,
        timeout: float | None = 1.0,
    ) -> None:
        super().__init__(name, devices)
        self.timeout = timeout or 1.0
        self.detectors: dict[str, DetectorProtocol] = {
            name: device
            for name, device in devices.items()
            if isinstance(device, DetectorProtocol)
        }

        # the internals of a signal backend are invoked in
        # a running event loop; we need to dispatch the
        # subscription coroutine to the background thread
        async def subscribe_to_buffers() -> None:
            for detector in self.detectors.values():
                detector.buffer.subscribe_reading(self.sigNewData.emit)

        run_coro(subscribe_to_buffers())

    def register_providers(self, container: VirtualContainer) -> None:
        """Register detector info as providers in the DI container.

        Also registers detector signals in the container.
        """
        container.detector_descriptors = providers.Object(self.devices_description())
        container.detector_readings = providers.Object(self.devices_configuration())
        container.detector_layer_specs = providers.Object(self.layer_specs())
        container.register_signals(self)

    def inject_dependencies(self, container: VirtualContainer) -> None:
        """Connect to the virtual container signals."""
        sigs = find_signals(container, ["sigPropertyChanged"])
        if "sigPropertyChanged" in sigs:
            sigs["sigPropertyChanged"].connect(self.configure)

    def layer_specs(self) -> dict[str, LayerSpec]:
        """Get the layer specifications for all detector devices."""
        specs: dict[str, LayerSpec] = {}
        for device in self.detectors.values():
            roi = run_coro(device.roi.get_value())
            dtype = run_coro(device.pixel_dtype.get_value())
            specs[device.name] = {"shape": roi[2:], "dtype": dtype}
        return specs

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

    def emit_new_data(self, data: dict[str, Reading[Any]]) -> None:
        """Emit new data readings from a detector.

        Strip the "buffer" suffix from the data key before emitting.
        """
        key = next(iter(data.keys()))
        if key.endswith("buffer"):
            new_key = key[: -len("buffer")]
            data[new_key] = data.pop(key)
        self.sigNewData.emit(data)

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
