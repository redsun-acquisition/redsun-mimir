from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from bluesky.protocols import Descriptor  # noqa: TC002
from dependency_injector import providers
from event_model import DocumentRouter
from ophyd_async.core import SignalRW
from redsun.engine import get_shared_loop
from redsun.log import Loggable
from redsun.presenter import Presenter
from redsun.utils import find_signals
from redsun.utils.descriptors import parse_key
from redsun.virtual import Signal

from redsun_mimir.protocols import DetectorProtocol  # noqa: TC001

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bluesky.protocols import Reading
    from event_model import Event
    from redsun.device import Device
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
    sigConfigurationConfirmed :
        Emitted after each individual setting change attempt.
        Carries detector name (``str``), setting name (``str``),
        and success status (``bool``).
    sigNewData :
        Emitted on each incoming event document.
        Carries a nested ``dict`` keyed by detector name.
    """

    sigNewConfiguration = Signal(str, dict[str, object])
    sigConfigurationConfirmed = Signal(str, str, bool)
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
        self.detectors = {
            name: device
            for name, device in devices.items()
            if isinstance(device, DetectorProtocol)
        }
        self.current_stream = ""
        self.packet: dict[str, dict[str, Any]] = {}

    def register_providers(self, container: VirtualContainer) -> None:
        r"""Register detector info as providers in the DI container.

        Injects two flat dicts keyed by the canonical ``prefix:name-property``
        scheme so the view can populate its tree directly at construction:

        - ``detector_descriptors``: merged ``describe_configuration()`` output
          from all detectors.
        - ``detector_readings``: merged ``read_configuration()`` output from
          all detectors.

        Also registers detector signals in the container.
        """
        loop = get_shared_loop()
        descriptors: dict[str, Descriptor] = {}
        readings: dict[str, Reading[Any]] = {}
        for detector in self.detectors.values():
            descriptors.update(
                asyncio.run_coroutine_threadsafe(
                    detector.describe_configuration(), loop
                ).result()
            )
            readings.update(
                asyncio.run_coroutine_threadsafe(
                    detector.read_configuration(), loop
                ).result()
            )

        container.detector_descriptors = providers.Object(descriptors)
        container.detector_readings = providers.Object(readings)
        container.register_signals(self)
        container.register_callbacks(self)

    def inject_dependencies(self, container: VirtualContainer) -> None:
        """Connect to the virtual container signals."""
        sigs = find_signals(container, ["sigPropertyChanged"])
        if "sigPropertyChanged" in sigs:
            sigs["sigPropertyChanged"].connect(self.configure)

    def configure(self, detector: str, config: dict[str, Any]) -> None:
        r"""Configure a detector with confirmation feedback.

        Update one or more configuration parameters of a detector by resolving
        each config key to the corresponding
        [`SignalRW`][ophyd_async.core.SignalRW] attribute on the device and
        calling its ``set()`` method directly.

        Emits ``sigNewConfiguration`` when successful and
        ``sigConfigurationConfirmed`` for each setting with success/failure.

        Parameters
        ----------
        detector :
            Bare device name as emitted by the view (e.g. ``"cam"``).
        config :
            Mapping of ophyd-async canonical signal keys to new values.
            Keys follow the ``"{device}-{attr_name}"`` convention, e.g.
            ``{"cam-exposure": 20.0}``.
        """
        device = self.detectors.get(detector)
        if device is None:
            self.logger.error(f"No detector found for label {detector!r}")
            return

        loop = get_shared_loop()
        for key, value in config.items():
            self.logger.debug(f"Configuring '{key}' of {detector!r} to {value!r}")
            future = asyncio.run_coroutine_threadsafe(
                self._set_and_wait(device, value, key), loop
            )
            try:
                success = future.result(timeout=self.timeout)
                if success:
                    self.sigNewConfiguration.emit(detector, {key: value})
                else:
                    self.logger.error(f"Failed to configure '{key}' of {detector!r}")
                self.sigConfigurationConfirmed.emit(detector, key, success)
            except TimeoutError:
                self.logger.error(f"Timeout configuring '{key}' of {detector!r}")
                self.sigConfigurationConfirmed.emit(detector, key, False)
            except Exception as e:
                self.logger.error(f"Exception configuring '{key}' of {detector!r}: {e}")
                self.sigConfigurationConfirmed.emit(detector, key, False)

    async def _set_and_wait(
        self, device: DetectorProtocol, value: Any, key: str
    ) -> bool:
        """Resolve *key* to a writable signal attribute and set it.

        The key is expected in ophyd-async ``"{device}-{attr}"`` form.
        The device-name prefix is stripped and the remainder used as the
        attribute name to look up on *device* (e.g. ``"cam-exposure"``
        resolves to ``device.exposure``).

        Returns
        -------
        bool
            ``True`` if the set completed without exception.
        """
        try:
            _, prop_name = parse_key(key)
        except ValueError:
            self.logger.error(f"Malformed config key: {key!r}")
            return False

        signal = getattr(device, prop_name, None)
        if not isinstance(signal, SignalRW):
            self.logger.error(
                f"No writable signal {prop_name!r} on device {device.name!r}"
            )
            return False

        try:
            await asyncio.wait_for(signal.set(value), timeout=self.timeout)
            return True
        except Exception as e:
            self.logger.warning(f"_set_and_wait failed for {key!r}: {e}")
            return False

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
