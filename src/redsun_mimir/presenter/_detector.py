from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import in_n_out as ino
from bluesky.utils import maybe_await
from event_model import DocumentRouter
from sunflare.log import Loggable
from sunflare.virtual import Signal

from redsun_mimir.common import ConfigurationDict  # noqa: TC001
from redsun_mimir.model import DetectorModelInfo  # noqa: TC001
from redsun_mimir.protocols import DetectorProtocol
from redsun_mimir.utils import filter_models

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bluesky.protocols import Descriptor, Reading
    from event_model import Event
    from sunflare.model import PModel
    from sunflare.virtual import VirtualBus

    from ._config import DetectorControllerInfo


info_store = ino.Store.create("detector_info")
config_store = ino.Store.create("detector_configuration")


class DetectorController(DocumentRouter, Loggable):
    """Controller for detector configuration.

    Parameters
    ----------
    ctrl_info : ``DetectorControllerInfo``
        Controller information.
    models : ``Mapping[str, PModel]``
        Mapping of model names to model instances.
    virtual_bus : ``VirtualBus``
        Reference to the virtual bus.

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
    sigNewData = Signal(str, object)

    def __init__(
        self,
        ctrl_info: DetectorControllerInfo,
        models: Mapping[str, PModel],
        virtual_bus: VirtualBus,
    ) -> None:
        super().__init__()
        self.ctrl_info = ctrl_info
        self.virtual_bus = virtual_bus

        self.detectors = filter_models(models, DetectorProtocol)

        self.hints = ["buffer", "roi"]

        info_store.register_provider(self.models_info)
        config_store.register_provider(self.models_configuration)

        # data stream name,
        # extracted from the incoming
        # descriptor document
        # whenever a new stream is declared
        self.current_stream = ""

    def models_info(self) -> dict[str, DetectorModelInfo]:
        """Get the models information.

        Returns
        -------
        dict[str, DetectorModelInfo]
            Mapping of model names to model information.
        """
        return {name: model.model_info for name, model in self.detectors.items()}

    def registration_phase(self) -> None:
        self.virtual_bus.register_signals(self)
        self.virtual_bus.register_callbacks(self)

    def connection_phase(self) -> None:
        self.virtual_bus.signals["DetectorWidget"]["sigPropertyChanged"].connect(
            self.configure
        )

    def models_configuration(self) -> ConfigurationDict:
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
                s.wait(self.ctrl_info.timeout)
                success = s.success

                if success:
                    self.sigNewConfiguration.emit(detector, {key: value})
                    self.logger.debug(f"Successfully configured '{key}' of {detector}")
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
        packet: dict[str, Any] = {}
        for key, value in doc["data"].items():
            detector_name, data_key = key.split(":")
            if detector_name in self.detectors and data_key in self.hints:
                if detector_name not in packet:
                    packet[detector_name] = {}
                packet[detector_name][data_key] = value
                self.sigNewData.emit(packet)
        return doc
