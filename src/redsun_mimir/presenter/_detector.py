from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from bluesky.protocols import Descriptor  # noqa: TC002
from bluesky.utils import maybe_await
from dependency_injector import providers
from event_model import DocumentRouter
from sunflare.log import Loggable
from sunflare.virtual import IsProvider, Signal, VirtualAware

from redsun_mimir.protocols import DetectorProtocol
from redsun_mimir.utils import filter_models, parse_key

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bluesky.protocols import Reading
    from dependency_injector.containers import DynamicContainer
    from event_model import Event
    from sunflare.device import Device
    from sunflare.virtual import VirtualBus


class DetectorPresenter(DocumentRouter, IsProvider, VirtualAware, Loggable):
    """Presenter for detector configuration and live data routing.

    Implements [`DocumentRouter`][event_model.DocumentRouter] to receive
    event documents emitted by the run engine and forward new image data
    to [`DetectorView`][redsun_mimir.view.DetectorView] via the virtual bus.

    Parameters
    ----------
    devices :
        Mapping of device names to device instances.
    virtual_bus :
        Reference to the virtual bus.
    timeout: float | None, keyword-only, optional
        Status object wait time in seconds
        for configuration confirmation.
        If `None`, waits indefinetely.
        Defaults to 1.0 seconds.
    hints: list[str] | None, keyword-only, optional
        List of data key suffixes to look for in event documents
        when routing data to the view. If `None`, no data will be routed.
        Defaults to `["buffer", "roi"]`.

    Attributes
    ----------
    sigNewConfiguration :
        Emitted after a detector setting is successfully applied.
        Carries the detector name (`str`) and a mapping of the
        changed setting to its new value (`dict[str, object]`).
    sigConfigurationConfirmed :
        Emitted after each individual setting change attempt.
        Carries detector name (`str`), setting name (`str`),
        and success status (`bool`).
    sigNewData :
        Emitted on each incoming event document.
        Carries a nested `dict` keyed by detector name, with inner
        keys `buffer` (raw image array) and `roi`
        (tuple `(x_start, x_end, y_start, y_end)`).
    """

    sigNewConfiguration = Signal(str, dict[str, object])
    sigConfigurationConfirmed = Signal(str, str, bool)
    sigNewData = Signal(object)

    def __init__(
        self,
        devices: Mapping[str, Device],
        virtual_bus: VirtualBus,
        /,
        timeout: float | None = 1.0,
        hints: list[str] | None = ["buffer", "roi"],
    ) -> None:
        super().__init__()
        self.timeout = timeout or 1.0
        self.hints = hints or ["buffer", "roi"]
        self.virtual_bus = virtual_bus
        self.detectors = filter_models(devices, DetectorProtocol)
        # data stream name,
        # extracted from the incoming
        # descriptor document
        # whenever a new stream is declared
        self.current_stream = ""
        self.packet: dict[str, dict[str, Any]] = {}

        self.virtual_bus.register_signals(self)
        self.virtual_bus.register_callbacks(self)

    def register_providers(self, container: DynamicContainer) -> None:
        r"""Register detector info as providers in the DI container.

        Injects two flat dicts keyed by the canonical ``prefix:name\\property``
        scheme so the view can populate its tree directly at construction:

        - ``detector_descriptors``: merged ``describe_configuration()`` output
          from all detectors.
        - ``detector_readings``: merged ``read_configuration()`` output from
          all detectors.
        """
        descriptors: dict[str, Descriptor] = {}
        readings: dict[str, Reading[Any]] = {}
        for detector in self.detectors.values():
            descriptors.update(
                asyncio.run(maybe_await(detector.describe_configuration()))
            )
            readings.update(asyncio.run(maybe_await(detector.read_configuration())))

        container.detector_descriptors = providers.Object(descriptors)
        container.detector_readings = providers.Object(readings)

    def connect_to_virtual(self) -> None:
        """Connect to the virtual bus signals."""
        self.virtual_bus.signals["DetectorView"]["sigPropertyChanged"].connect(
            self.configure
        )

    def configure(self, detector: str, config: dict[str, Any]) -> None:
        r"""Configure a detector with confirmation feedback.

        Update one or more configuration parameters of a detector.

        Emits ``sigNewConfiguration`` signal when successful,
        with the detector name and the new configuration.
        Emits ``sigConfigurationConfirmed`` signal for each setting
        with confirmation of success or failure.

        Parameters
        ----------
        detector : ``str``
            Device label (``prefix:name``) as emitted by
            :class:`~redsun_mimir.view.DetectorView`.
        config : ``dict[str, Any]``
            Mapping of canonical ``prefix:name\\property`` keys to new values.

        """
        # device_label is "name"; self.detectors is keyed by bare name
        try:
            bare_name, _ = parse_key(next(iter(config)))
        except (StopIteration, ValueError):
            # fall back to treating detector arg as the bare name directly
            bare_name = detector

        device = self.detectors.get(bare_name)
        if device is None:
            self.logger.error(
                f"No detector found for label {detector!r} (bare name {bare_name!r})"
            )
            return

        for key, value in config.items():
            self.logger.debug(f"Configuring '{key}' of {detector} to {value}")
            s = device.set(value, propr=key)
            try:
                s.wait(self.timeout)
                success = s.success

                if success:
                    self.sigNewConfiguration.emit(detector, {key: value})
                else:
                    self.logger.error(
                        f"Failed to configure '{key}' of {detector}: {s.exception()}"
                    )
                self.sigConfigurationConfirmed.emit(detector, key, success)

            except Exception as e:
                self.logger.error(f"Exception configuring '{key}' of {detector}: {e}")
                self.sigConfigurationConfirmed.emit(detector, key, False)

    def event(self, doc: Event) -> Event:
        """Process new event documents.

        Parameters
        ----------
        doc : ``Event``
            The event document.
        """
        for key, value in doc["data"].items():
            parts = key.split("\\")
            if len(parts) < 2:
                continue
            obj_name, hint = parts[0], parts[1]
            if hint in self.hints:
                self.packet.setdefault(obj_name, {})
                self.packet[obj_name][hint] = value
        self.sigNewData.emit(self.packet)
        return doc
