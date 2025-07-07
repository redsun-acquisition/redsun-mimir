from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import in_n_out as ino
from bluesky.utils import maybe_await
from sunflare.log import Loggable
from sunflare.virtual import Signal

from redsun_mimir.model import DetectorModelInfo  # noqa: TC001
from redsun_mimir.protocols import DetectorProtocol

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bluesky.protocols import Descriptor, Reading
    from sunflare.model import ModelProtocol
    from sunflare.virtual import VirtualBus

    from ._config import DetectorControllerInfo

store = ino.Store.create("DetectorModelInfo")


class ImageController(Loggable):
    """Controller for detector configuration.

    Parameters
    ----------
    ctrl_info : ``DetectorControllerInfo``
        Controller information.
    models : ``Mapping[str, ModelProtocol]``
        Mapping of model names to model instances.
    virtual_bus : ``VirtualBus``
        Reference to the virtual bus.

    Attributes
    ----------
    sigNewConfiguration : ``Signal[str, dict[str, object]]``
        Signal for new configuration.
        - ``str``: detector name.
        - ``dict[str, object]``: new configuration.
    sigNewDetectorDescriptorReading : ``Signal[str, dict[str, object]]``
        Signal for detector configuration reading.
        - ``str``: detector name.
        - ``dict[str, object]``: configuration reading.
    sigNewDetectorDescriptor : ``Signal[str, dict[str, object]]``
        Signal for detector configuration descriptor.
        - ``str``: detector name.
        - ``dict[str, object]``: configuration descriptor.
    sigConfigurationConfirmed : ``Signal[str, str, bool]``
        Signal for configuration confirmation.
        - ``str``: detector name.
        - ``str``: setting name.
        - ``bool``: success status.

    """

    sigNewConfiguration = Signal(str, dict[str, object])
    sigNewDetectorDescriptorReading = Signal(str, dict[str, object])
    sigNewDetectorDescriptor = Signal(str, dict[str, object])
    sigConfigurationConfirmed = Signal(str, str, bool)

    def __init__(
        self,
        ctrl_info: DetectorControllerInfo,
        models: Mapping[str, ModelProtocol],
        virtual_bus: VirtualBus,
    ) -> None:
        self.ctrl_info = ctrl_info
        self.virtual_bus = virtual_bus

        self.detectors = {
            name: model
            for name, model in models.items()
            if isinstance(model, DetectorProtocol)
        }

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

    def connection_phase(self) -> None:
        self.virtual_bus["ImageWidget"]["sigConfigRequest"].connect(
            self._provide_configuration
        )
        self.virtual_bus["ImageWidget"]["sigPropertyChanged"].connect(self.configure)

    def _provide_configuration(self) -> None:
        for name in self.detectors.keys():
            self.describe_configuration(name)
        for name in self.detectors.keys():
            self.read_configuration(name)

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

    def read_configuration(self, detector: str) -> None:
        """Read the configuration of a detector.

        The configuration is emitted via the ``sigNewDetectorDescriptorReading`` signal.

        Parameters
        ----------
        detector : ``str``
            Detector name.

        """

        async def _async_helper() -> dict[str, Reading[Any]]:
            return await maybe_await(self.detectors[detector].read_configuration())

        self.sigNewDetectorDescriptorReading.emit(
            detector, asyncio.run(_async_helper())
        )

    def describe_configuration(self, detector: str) -> None:
        """Read the configuration description of a detector.

        The configuration description is emitted
        via the ``sigNewDetectorDescriptor`` signal.

        Parameters
        ----------
        detector : ``str``
            Detector name.

        """

        async def _async_helper() -> dict[str, Descriptor]:
            return await maybe_await(self.detectors[detector].describe_configuration())

        self.sigNewDetectorDescriptor.emit(detector, asyncio.run(_async_helper()))
