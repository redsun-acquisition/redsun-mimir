from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from bluesky.protocols import Descriptor, Reading
from bluesky.utils import maybe_await
from sunflare.log import Loggable
from sunflare.virtual import Signal

from ..protocols import DetectorProtocol

if TYPE_CHECKING:
    from typing import Mapping

    from sunflare.model import ModelProtocol
    from sunflare.virtual import VirtualBus

    from ._config import DetectorControllerInfo


class DetectorController(Loggable):
    sigNewConfiguration = Signal(str, dict[str, bool])
    sigDetectorConfigReading = Signal(str, dict[str, Reading[Any]])
    sigDetectorConfigDescriptor = Signal(str, dict[str, Descriptor])

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

    def registration_phase(self) -> None:
        self.virtual_bus.register_signals(self)

    def connection_phase(self) -> None:
        self.virtual_bus["DetectorWidget"]["sigConfigRequest"].connect()

    def _provide_configuration(self) -> None:
        for name in self.detectors.keys():
            self.describe_configuration(name)
            self.read_configuration(name)

    def configure(self, detector: str, config: dict[str, Any]) -> dict[str, bool]:
        """Configure a detector.

        Update one or more configuration parameters of a detector.

        Emits the ``sigNewConfiguration`` signal when the configuration
        is completed, returning a mapping of configuration parameters
        to success status.

        Parameters
        ----------
        detector : ``str``
            Detector name.
        config : ``dict[str, Any]``
            Mapping of configuration parameters to new values.

        Returns
        -------
        ``dict[str, bool]``
            Mapping of configuration parameters to success status.

        """
        success_map: dict[str, bool] = {}
        for key, value in config.items():
            self.debug(f"Configuring {key} of {detector} to {value}")
            s = self.detectors[detector].set(value, prop=key)
            try:
                s.wait(self.ctrl_info.timeout)
            except Exception as e:
                self.exception(f"Failed to configure {key} of {detector}: {e}")
                s.set_exception(e)
            finally:
                if not s.success:
                    self.error(
                        f"Failed to configure {key} of {detector}: {s.exception()}"
                    )
                success_map[key] = s.success
        self.sigNewConfiguration.emit(detector, success_map)
        return success_map

    def read_configuration(self, detector: str) -> None:
        """Read the configuration of a detector.

        The configuration is emitted via the ``sigDetectorConfigReading`` signal.

        Parameters
        ----------
        detector : ``str``
            Detector name.

        """

        async def _async_helper() -> dict[str, Reading[Any]]:
            return await maybe_await(self.detectors[detector].read_configuration())

        self.sigDetectorConfigReading.emit(detector, asyncio.run(_async_helper()))

    def describe_configuration(self, detector: str) -> None:
        """Read the configuration description of a detector.

        The configuration description is emitted
        via the ``sigDetectorConfigDescriptor`` signal.

        Parameters
        ----------
        detector : ``str``
            Detector name.

        """

        async def _async_helper() -> dict[str, Descriptor]:
            return await maybe_await(self.detectors[detector].describe_configuration())

        self.sigDetectorConfigDescriptor.emit(detector, asyncio.run(_async_helper()))
