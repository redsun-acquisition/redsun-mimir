from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from bluesky.protocols import Descriptor  # noqa: TC002
from bluesky.utils import maybe_await
from dependency_injector import providers
from event_model import DocumentRouter
from sunflare.log import Loggable
from sunflare.virtual import IsProvider, Signal, VirtualAware

from redsun_mimir.common import ConfigurationDict  # noqa: TC001
from redsun_mimir.protocols import DetectorProtocol
from redsun_mimir.utils import filter_models

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bluesky.protocols import Reading
    from dependency_injector.containers import DynamicContainer
    from event_model import Event
    from sunflare.device import Device
    from sunflare.virtual import VirtualBus


class DetectorController(DocumentRouter, IsProvider, VirtualAware, Loggable):
    """Controller for detector configuration.

    Parameters
    ----------
    devices : ``Mapping[str, Device]``
        Mapping of device names to device instances.
    virtual_bus : ``VirtualBus``
        Reference to the virtual bus.
    **kwargs : Any
        Additional keyword arguments.
        - ``timeout`` (float | None): Timeout in seconds.

    Attributes
    ----------
    sigNewConfiguration : ``Signal[str, dict[str, object]]``
        Signal for new configuration.
        - ``str``: detector name.
        - ``dict[str, object]``: new configuration.
    sigConfigurationConfirmed : ``Signal[str, str, bool]``
        Signal for configuration confirmation.
        - ``str``: detector name.
        - ``str``: setting name.
        - ``bool``: success status.
    sigNewData : ``Signal[dict[str, dict[str, Any]]]``
        Signal for new data; the presenter should actively
        listen to new incoming data from a presenter equipped
        with a run engine capable of emitting new documents.
        - ``dict[str, dict[str, Any]]``: nested dictionary:
            - outer key: detector name.
            - inner keys: raw data buffer (`'buffer'`) and region of interest (`'roi'`).
            - `roi` formatted as `(x_start, x_end, y_start, y_end)`.
    """

    sigNewConfiguration = Signal(str, dict[str, object])
    sigConfigurationConfirmed = Signal(str, str, bool)
    sigNewData = Signal(object)

    def __init__(
        self,
        devices: Mapping[str, Device],
        virtual_bus: VirtualBus,
        /,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        self._timeout: float | None = kwargs.get("timeout", None)
        self.virtual_bus = virtual_bus
        self.devices = devices

        self.detectors = filter_models(devices, DetectorProtocol)

        self.hints = ["buffer", "roi"]

        # data stream name,
        # extracted from the incoming
        # descriptor document
        # whenever a new stream is declared
        self.current_stream = ""
        self.packet: dict[str, dict[str, Any]] = {}

    def register_providers(self, container: DynamicContainer) -> None:
        """Register detector info as providers in the DI container."""
        container.detector_configuration = providers.Object(
            self.get_models_configuration()
        )
        container.detector_descriptions = providers.Object(
            self.get_models_description()
        )
        self.virtual_bus.register_signals(self)
        self.virtual_bus.register_callbacks(self)

    def connect_to_virtual(self) -> None:
        """Connect to the virtual bus signals."""
        self.virtual_bus.signals["DetectorWidget"]["sigPropertyChanged"].connect(
            self.configure
        )

    def get_models_configuration(self) -> ConfigurationDict:
        """Get the configuration of all detectors."""
        descriptors = {
            name: self.describe_configuration(name) for name in self.detectors.keys()
        }
        readings = {
            name: self.read_configuration(name) for name in self.detectors.keys()
        }

        config: ConfigurationDict = {
            "descriptors": descriptors,
            "readings": readings,
        }

        return config

    def get_models_description(self) -> dict[str, dict[str, Descriptor]]:
        """Get reading descriptions of all detectors."""
        descriptions = {
            name: detector.describe() for name, detector in self.detectors.items()
        }
        return descriptions  # type: ignore

    def configure(self, detector: str, config: dict[str, Any]) -> None:
        """Configure a detector with confirmation feedback.

        Update one or more configuration parameters of a detector.

        Emits ``sigNewConfiguration`` signal when successful,
        with the detector name and the new configuration.
        Emits ``sigConfigurationConfirmed`` signal for each setting
        with confirmation of success or failure.

        Parameters
        ----------
        detector : ``str``
            Detector name.
        config : ``dict[str, Any]``
            Mapping of configuration parameters to new values.

        """
        for key, value in config.items():
            self.logger.debug(f"Configuring '{key}' of {detector} to {value}")
            s = self.detectors[detector].set(value, propr=key)
            try:
                s.wait(self._timeout)
                success = s.success

                if success:
                    self.sigNewConfiguration.emit(detector, {key: value})
                else:
                    self.logger.error(
                        f"Failed to configure '{key}' of {detector}: {s.exception()}"
                    )
                # Emit confirmation for each setting
                self.sigConfigurationConfirmed.emit(detector, key, success)

            except Exception as e:
                self.logger.error(f"Exception configuring '{key}' of {detector}: {e}")
                self.sigConfigurationConfirmed.emit(detector, key, False)

    async def _describe_config_async(self, detector: str) -> dict[str, Descriptor]:
        return await maybe_await(self.detectors[detector].describe_configuration())

    async def _read_config_async(self, detector: str) -> dict[str, Reading[Any]]:
        return await maybe_await(self.detectors[detector].read_configuration())

    def read_configuration(self, detector: str) -> dict[str, Reading[Any]]:
        """Read the configuration of a detector.

        Parameters
        ----------
        detector : ``str``
            Detector name.

        Returns
        -------
        dict[str, Reading[Any]]
            Mapping of configuration parameters to their readings.
        """
        return asyncio.run(self._read_config_async(detector))

    def describe_configuration(self, detector: str) -> dict[str, Descriptor]:
        """Read the configuration description of a detector.

        Parameters
        ----------
        detector : ``str``
            Detector name.

        Returns
        -------
        dict[str, Descriptor]
            Mapping of configuration parameters to their descriptors.

        """
        return asyncio.run(self._describe_config_async(detector))

    def event(self, doc: Event) -> Event:
        """Process new event documents.

        Parameters
        ----------
        doc : ``Event``
            The event document.
        """
        for key, value in doc["data"].items():
            obj_name, data_key = key.split(":")
            if data_key in self.hints:
                self.packet.setdefault(obj_name, {})
                self.packet[obj_name][data_key] = value
        self.sigNewData.emit(self.packet)
        return doc
