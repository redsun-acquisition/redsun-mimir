from __future__ import annotations

import time
from typing import TYPE_CHECKING, cast

from bluesky.protocols import Descriptor, Pausable
from pymmcore_plus import CMMCorePlus as Core
from pymmcore_plus import DeviceType
from sunflare.engine import Status
from sunflare.log import Loggable

from redsun_mimir.protocols import DetectorProtocol

if TYPE_CHECKING:
    from typing import Any, ClassVar

    from bluesky.protocols import Descriptor, Reading

    from ._config import MMCoreCameraModelInfo


class MMCoreCameraModel(DetectorProtocol, Pausable, Loggable):
    """Demo camera wrapper for CMMCorePlus.

    This class is a hack because it will fail initialization if
    a second camera object of the same class is created; this
    is because at this time MMCore does not support multiple
    instances of the same camera device.
    """

    # class variable to track initialization status;
    # multiple instances are not supported
    initialized: ClassVar[bool] = False

    # Define which properties to expose in configuration
    EXPOSED_PROPERTIES: ClassVar[set[str]] = {
        "Exposure",
        "DisplayImageNumber",
        "PixelType",
    }

    def __init__(self, name: str, model_info: MMCoreCameraModelInfo) -> None:
        self._name = name
        self._model_info = model_info
        self._core = Core.instance()
        try:
            if MMCoreCameraModel.initialized:
                raise RuntimeError(
                    "MMCoreCameraModel has already been initialized once; "
                    "multiple instances are not supported."
                )

            self._core.loadDevice(name, model_info.adapter, model_info.device)
            self._core.initializeAllDevices()

            # use device object for property manipulation
            self._device = self._core.getDeviceObject(
                name, device_type=DeviceType.Camera
            )
            MMCoreCameraModel.initialized = True
        except Exception as e:
            self.logger.error(f"Failed to initialize device {name}")
            raise e

        # TODO: make ROI management more robust
        x, y, w, h = self._device.getROI()

        if (x, y) != (0, 0):
            self._device.setROI(0, 0, w, h)
        if self.model_info.sensor_shape > (h, w):
            self._device.setROI(
                x, y, self.model_info.sensor_shape[1], self.model_info.sensor_shape[0]
            )

        self.roi = (0, 0, *self.model_info.sensor_shape)
        self._device_schema = self._device.schema()
        self._buffer_key = f"{self.name}:buffer"
        self._roi_key = f"{self.name}:roi"

    def set(self, value: Any, **kwargs: Any) -> Status:
        """Set a property of the detector.

        Parameters
        ----------
        value: `Any`
            The value to set for the property.
        **kwargs: `dict[str, Any]`
            Additional keyword arguments, including the property name.

        Returns
        -------
        `Status`
            Status of the operation.
        """
        s = Status()
        propr = kwargs.get("propr", None)
        if propr:
            propr = cast("str", propr).split(":")[1]
        else:
            s.set_exception(ValueError("No property specified."))
        if propr in self._device_schema["properties"]:
            self._core.setProperty(self.name, propr, value)
            s.set_finished()
            self.logger.debug(f"Set {propr} to {value}.")
        elif propr == "roi":
            # TODO: should we validate the ROI here?
            self._core.setROI(self.name, *value)
            self.roi = tuple(value)
            s.set_finished()
            self.logger.debug(f"Set ROI to {value}.")
        else:
            s.set_exception(ValueError(f"Property '{propr}' not found."))
        return s

    def describe_configuration(self) -> dict[str, Descriptor]:
        schema = self._device.schema()
        config_descriptor: dict[str, Descriptor] = {}
        for key, value in schema["properties"].items():
            # Filter to only include exposed properties
            if key not in self.EXPOSED_PROPERTIES:
                continue

            descriptor_key = f"{self.name}:{key}"
            config_descriptor[descriptor_key] = {
                "source": "properties",
                # the "type" key is JSON-compatible,
                # so we can skip the type check here
                "dtype": value["type"],  # type: ignore[typeddict-item]
                "shape": [],
            }
            maximum: float | None = value.get("maximum", None)
            minimum: float | None = value.get("minimum", None)
            if maximum is not None and minimum is not None:
                config_descriptor[descriptor_key]["limits"] = {
                    "control": {
                        "low": value["minimum"],
                        "high": value["maximum"],
                    }
                }
        config_descriptor.update(
            self.model_info.describe_configuration(source="model_info/readonly")
        )
        return config_descriptor

    def read_configuration(self) -> dict[str, Reading[Any]]:
        timestamp = time.time()
        config = self.model_info.read_configuration(timestamp)
        for prop in self._device.properties:
            # Filter to only include exposed properties
            if prop.name not in self.EXPOSED_PROPERTIES:
                continue

            config[f"{self.name}:{prop.name}"] = {
                "value": prop.value,
                "timestamp": timestamp,
            }
        return config

    def stage(self) -> Status:
        s = Status()
        try:
            if not self._core.isSequenceRunning():
                self._core.startContinuousSequenceAcquisition()
                self.logger.debug(f"Staged {self.name}.")
            s.set_finished()
        except Exception as e:
            self.logger.error(f"Failed to stage {self.name}: {e}")
            s.set_exception(e)
        return s

    def unstage(self) -> Status:
        s = Status()
        try:
            if self._core.isSequenceRunning():
                self._core.stopSequenceAcquisition(self.name)
                self.logger.debug(f"Unstaged {self.name}.")
            s.set_finished()
        except Exception as e:
            self.logger.error(f"Failed to unstage {self.name}: {e}")
            s.set_exception(e)
        return s

    def kickoff(self) -> Status:
        """Kickoff a continuous acquisition.

        For micro-manager, this is equivalent to staging the detector,
        as acquisition doesn't block the main thread.
        """
        return self.stage()

    def complete(self) -> Status:
        """Complete the continuous acquisition.

        For micro-manager, this is equivalent to unstaging the detector,
        as acquisition doesn't block the main thread.
        """
        return self.unstage()

    def pause(self) -> None:
        """Pause the acquisition.

        This translates to stopping the sequence acquisition.
        """
        self._core.stopSequenceAcquisition(self.name)

    def resume(self) -> None:
        """Resume the acquisition.

        This translates to starting the sequence acquisition.
        """
        self._core.startContinuousSequenceAcquisition()

    def read(self) -> dict[str, Reading[Any]]:
        """Read an acquired image.

        Returns
        -------
        dict[str, Reading[Any]]
            A dictionary containing the acquired image and ROI.

        Raises
        ------
        RuntimeError
            If acquisition is not running.
        """
        # there are no clear information
        # about the metadata associated with
        # each acquired image, requires investigation
        if not self._core.isSequenceRunning():
            raise RuntimeError(f"Acquisition is not running for detector {self.name}.")
        while self._core.getRemainingImageCount() == 0:
            # keep polling until an image is available;
            # just wait a bit to avoid busy waiting;
            time.sleep(0.001)
        img = self._core.popNextImage()
        stamp = time.time()
        return {
            self._buffer_key: {"value": img, "timestamp": stamp},
            self._roi_key: {"value": self.roi, "timestamp": stamp},
        }

    def describe(self) -> dict[str, Descriptor]:
        """Describe the data produced by the detector.

        Returns
        -------
        dict[str, dict[str, Descriptor]]
            A dictionary describing the data produced by the detector.
        """
        width, height = self._core.getImageWidth(), self._core.getImageHeight()
        return {
            self._buffer_key: {
                "source": "data",
                "dtype": "array",
                "shape": [height, width],
            },
            self._roi_key: {
                "source": "data",
                "dtype": "array",
                "shape": [4],
            },
        }

    @property
    def name(self) -> str:
        return self._name

    @property
    def model_info(self) -> MMCoreCameraModelInfo:
        return self._model_info

    @property
    def parent(self) -> None:
        return None
