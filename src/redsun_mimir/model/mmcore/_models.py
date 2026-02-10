from __future__ import annotations

import threading as th
import time
from typing import TYPE_CHECKING, TypedDict, cast

import numpy as np
from pymmcore_plus import CMMCorePlus as Core
from pymmcore_plus import DeviceType
from sunflare.engine import Status
from sunflare.log import Loggable

from redsun_mimir.model.utils import RingBuffer
from redsun_mimir.protocols import DetectorProtocol
from redsun_mimir.storage import ZarrWriter

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any, ClassVar, Iterator

    from bluesky.protocols import Descriptor, Reading, StreamAsset

    from ._config import MMCoreCameraModelInfo


class PrepareKwargs(TypedDict):
    """Keyword arguments for preparing the model for flight."""

    capacity: int
    """The number of frames to store; if 0, unlimited."""

    store_path: Path
    """The path to store the acquired data."""

    write_forever: bool
    """When True, write data indefinitely until stopped. Overrides `capacity`."""


class MMCoreCameraModel(DetectorProtocol, Loggable):
    """Demo camera wrapper for CMMCorePlus.

    This class is a hack because it will fail initialization if
    a second camera object of the same class is created.

    This is because  MMCore does not yet support multiple
    cameras without the `MultiCameraAdapter` integration,
    which introduces complexities that we are not ready to deal with yet.
    """

    # class variable to track initialization status;
    # multiple instances are not supported
    initialized: ClassVar[bool] = False

    def __init__(self, name: str, model_info: MMCoreCameraModelInfo) -> None:
        self._name = name
        self._model_info = model_info
        self._core = Core.instance()
        self._pixelprop = list(model_info.numpy_dtype.keys())[0]
        try:
            if MMCoreCameraModel.initialized:
                raise RuntimeError(
                    "MMCoreCameraModel has already been initialized once; "
                    "multiple instances are not supported."
                )
            self._core.loadDevice(name, model_info.adapter, model_info.device)
            self._core.initializeDevice(name)
            self._core.setCameraDevice(name)

            # use device object for property manipulation
            self._device = self._core.getDeviceObject(
                name, device_type=DeviceType.Camera
            )
            MMCoreCameraModel.initialized = True
        except Exception as e:
            self.logger.error(f"Failed to initialize device {name}")
            raise e

        # always reset the ROI to the full frame
        # on initialization; if the input specifies a smaller ROI,
        # update it
        self._core.clearROI()
        full_frame = self._device.getROI()[2:]

        if (
            model_info.sensor_shape[0] > full_frame[0]
            or model_info.sensor_shape[1] > full_frame[1]
        ):
            raise ValueError(
                f"Requested sensor shape {model_info.sensor_shape[2:]} exceeds "
                f"full frame size {full_frame[0]}x{full_frame[1]} of the camera."
            )

        if model_info.sensor_shape[0:] != tuple(self._device.getROI()[2:]):
            self._device.setROI(0, 0, *model_info.sensor_shape[0:])

        if model_info.defaults:
            for prop, value in model_info.defaults.items():
                # if the property is not in the allowed properties, skip it
                if prop not in model_info.allowed_properties:
                    continue
                self._core.setProperty(name, prop, value)

        self._core.setExposure(self.name, model_info.starting_exposure)

        self.roi = (0, 0, *self.model_info.sensor_shape)
        self._device_schema = self._device.schema()
        self._buffer_key = f"{self.name}:buffer"
        self._roi_key = f"{self.name}:roi"
        self._buffer_stream_key = f"{self.name}:buffer:stream"
        self._fly_start = th.Event()
        self._fly_stop = th.Event()
        self._staged = th.Event()
        self._current_exposure: float = 0.0

        # Writer for storage
        self._writer = ZarrWriter.get("zarr-writer")
        self._stream_descriptors: dict[str, Descriptor] = {}

        self._complete_status = Status()
        self._assets_collected = False  # Track if stream assets have been collected

        self.logger.debug(f"Initialized {model_info.adapter}\{model_info.device}")

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
        elif propr == "exposure (ms)":
            self._core.setExposure(self.name, value)
            s.set_finished()
        elif propr == "roi":
            # TODO: should we validate the ROI here?
            self._core.setROI(self.name, *value)
            self.roi = tuple(value)
            s.set_finished()
        else:
            s.set_exception(ValueError(f"Property '{propr}' not found."))

        return s

    def describe_configuration(self) -> dict[str, Descriptor]:
        schema = self._device.schema()
        config_descriptor: dict[str, Descriptor] = {}
        for key, value in schema["properties"].items():
            # Filter to only include exposed properties
            if key not in self.model_info.allowed_properties:
                continue

            choices: list[str] = []
            if key in self.model_info.enum_map:
                choices = list(self.model_info.enum_map[key])
            elif value["type"] == "string":
                choices = value.get("enum", [])

            descriptor_key = f"{self.name}:{key}"
            config_descriptor[descriptor_key] = {
                "source": "properties",
                # the "type" key is JSON-compatible,
                # so we can skip the type check here
                "dtype": value["type"],  # type: ignore[typeddict-item]
                "shape": [],
                "choices": choices,
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
        config_descriptor.pop("allowed_properties", None)
        config_descriptor.pop("enum_map", None)
        config_descriptor.pop("numpy_dtype", None)
        config_descriptor.pop("defaults", None)
        config_descriptor.pop("starting_exposure", None)
        config_descriptor.pop("exposure_limits", None)

        config_descriptor[f"{self.name}:exposure (ms)"] = {
            "source": "settings",
            "dtype": "number",
            "shape": [],
            "limits": {
                "control": {
                    "low": self.model_info.exposure_limits[0],
                    "high": self.model_info.exposure_limits[1],
                }
            },
        }

        return config_descriptor

    def read_configuration(self) -> dict[str, Reading[Any]]:
        timestamp = time.time()
        config = self.model_info.read_configuration(timestamp)

        # the following configuration parameters are redundant
        # as they are already included in the properties schema,
        # but model_info.read_configuration() will include them by default;
        # in the future model_info will not exist
        config.pop("allowed_properties", None)
        config.pop("enum_map", None)
        config.pop("numpy_dtype", None)
        config.pop("defaults", None)
        config.pop("starting_exposure", None)
        config.pop("exposure_limits", None)

        for prop in self._device.properties:
            # Filter to only include exposed properties
            if prop.name not in self.model_info.allowed_properties:
                continue

            config[f"{self.name}:{prop.name}"] = {
                "value": prop.value,
                "timestamp": timestamp,
            }
        config[f"{self.name}:exposure (ms)"] = {
            "value": self._device.getExposure(),
            "timestamp": timestamp,
        }
        return config

    def stage(self) -> Status:
        s = Status()

        # convert the exposure time from milliseconds to seconds
        # for use in the streaming thread and the image availability wait
        self._current_exposure = self._core.getExposure() / 1000.0
        try:
            self._core.startContinuousSequenceAcquisition(self._current_exposure * 1000)
            self.logger.debug(f"Staged {self.name}.")
            s.set_finished()
        except Exception as e:
            s.set_exception(e)
        return s

    def unstage(self) -> Status:
        s = Status()
        try:
            self._core.stopSequenceAcquisition(self.name)
            self.logger.debug(f"Unstaged {self.name}.")
            s.set_finished()
        except Exception as e:
            s.set_exception(e)
        return s

    def prepare(self, value: PrepareKwargs) -> Status:
        """Prepare the detector for acquisition.

        Parameters
        ----------
        value: PrepareKwargs
            Keyword arguments for preparation, including:
            - capacity: int
                The number of frames to store; if 0, unlimited.
            - store_path: Path
                The path to store the acquired data.
            - write_forever: bool
                If True, write data indefinitely until stopped.
                Overrides `capacity`.
        """
        s = Status()
        self._fly_start.clear()
        self._fly_stop.clear()
        try:
            width, height = self._core.getImageWidth(), self._core.getImageHeight()

            # TODO: this is horrible; we need a better way
            # to manage the mapping from camera properties to numpy dtypes
            dtype = self._numpy_dtype = self.model_info.numpy_dtype[self._pixelprop][
                self._core.getProperty(self.name, self._pixelprop)
            ]
            capacity = value.get("capacity", 0)
            store_path = value.get("store_path")
            write_forever = value.get("write_forever")

            if write_forever:
                # override any previous setting
                capacity = 0  # unlimited

            # Update source info for this camera
            self._writer.update_source(
                name=self.name,
                dtype=np.dtype(dtype),
                shape=(height, width),
            )
            self._frame_sink = self._writer.prepare(self.name, store_path, capacity)

            # create 1 frame ring buffer to
            # allow reading to continue while streaming
            self._read_buffer = RingBuffer(
                max_capacity=1, dtype=(dtype, (height, width))
            )

            self._thread = th.Thread(
                target=self._stream_to_disk,
                kwargs={
                    "frames": capacity,
                },
                daemon=True,
            )
            self._thread.start()
        except Exception as e:
            s.set_exception(e)
        else:
            s.set_finished()
        return s

    def kickoff(self) -> Status:
        """Kickoff a continuous acquisition.

        Starts a background thread that continously
        streams images from the internal ring buffer
        into disk.

        Kickoff requires that stage() has been called
        to arm the device and prepare() has been called
        to create the storage backend.

        Otherwise, the status will report an exception.

        Returns
        -------
        Status
            Status of the operation.
        """
        s = Status()

        def _clear_flags(_: Status) -> None:
            """Clear the flying flags when done."""
            self._fly_start.clear()
            self._fly_stop.clear()

        # we also prepare a status for complete()
        if self._complete_status.done:
            # recreate the status if it's already done
            self._complete_status = Status()
        self._complete_status.add_callback(_clear_flags)

        # Reset the assets collected flag for this new flight
        self._assets_collected = False

        if not self._core.isSequenceRunning():
            s.set_exception(
                RuntimeError(
                    "Acquisition is not running (stage() should be called first). "
                )
            )
        if not self._thread:
            s.set_exception(
                RuntimeError(
                    "Storage backend is not prepared (prepare() should be called first). "
                )
            )
        else:
            # acquisition is already running
            # and ring buffer is ready:
            # start the background thread
            self._writer.kickoff()
            self._fly_start.set()
            s.set_finished()
        return s

    def complete(self) -> Status:
        """Complete the continuous acquisition.

        Stops the background thread that streams images
        from the internal ring buffer into disk and
        closes the storage backend.

        If kickoff() was not called before, the status
        will report an exception.

        Returns
        -------
        Status
            Status of the operation.
        """
        if self._complete_status.done:
            return self._complete_status

        if not self._fly_start.is_set():
            self._complete_status.set_exception(
                RuntimeError("Not flying; kickoff() must be called first. ")
            )
            return self._complete_status
        # stop the streaming thread;
        # this will also set the status
        # to finished when done
        self._fly_stop.set()
        return self._complete_status

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
        if not self._fly_start.is_set():
            # not flying; read the latest image from core buffer
            self._wait_image_awailable()
            img = self._core.popNextImage()
        else:
            # peek the ring buffer head
            img = self._read_buffer.peek()
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
        # Base description without stream assets (for live reads)
        describe: dict[str, Descriptor] = {
            self._buffer_key: {
                "source": "data",
                "dtype": "array",
                "shape": [1, *self.roi[3:4]],
            },
            self._roi_key: {
                "source": "data",
                "dtype": "array",
                "shape": [4],
            },
        }
        return describe

    def describe_collect(
        self,
    ) -> dict[str, Descriptor]:
        """Describe the data collected during acquisition.

        Returns
        -------
        dict[str, Descriptor]
            A dictionary describing the data collected during acquisition.
        """
        width, height = self._core.getImageWidth(), self._core.getImageHeight()
        return {
            self._buffer_stream_key: {
                "source": "data",
                "dtype": "array",
                "shape": [None, width, height],
                "external": "STREAM:",
            }
        }

    def collect_asset_docs(self, index: int | None = None) -> Iterator[StreamAsset]:
        """Collect the assets stored on disk.

        Only emits StreamResource and StreamDatum if there are frames written to disk
        from a flying/streaming operation AND the flight has completed (not currently flying).

        Parameters
        ----------
        index : int | None
            If provided, only report frames up to this index.
            If None, report all frames written so far.

        Yields
        ------
        StreamAsset
        - A tuple containing the stream resource information.
        - These are encapsulated into two separate elements:
          - ("stream_resource", StreamResource) - emitted only on first call
          - ("stream_datum", StreamDatum) - emitted on each call with incremental indices
        """
        # Only emit asset docs if we're not currently flying
        # This prevents emitting assets during read_while_waiting (while streaming is active)
        # Assets should only be emitted after complete() is called
        if self._fly_start.is_set():
            return

        if not self._complete_status.done:
            return

        # Don't emit assets if they've already been collected
        if self._assets_collected:
            return

        frames_written = self._writer.get_indices_written(self.name)
        if frames_written == 0:
            return

        # Determine how many frames to report
        if index is not None:
            frames_to_report = min(index, frames_written)
        else:
            frames_to_report = frames_written

        # Mark that we're collecting assets
        self._assets_collected = True

        # Delegate to writer
        yield from self._writer.collect_stream_docs(self.name, frames_to_report)

    def get_index(self) -> int:
        """Return the number of frames written since last flight."""
        return self._writer.get_indices_written(self.name)

    @property
    def name(self) -> str:
        return self._name

    @property
    def model_info(self) -> MMCoreCameraModelInfo:
        return self._model_info

    @property
    def parent(self) -> None:
        return None

    def _stream_to_disk(self, *, frames: int) -> None:
        """Stream data from the camera to disk.

        The thread is started in the camera's prepare() method,
        kicked off in the kickoff() method, and stopped in the complete() method.

        Parameters
        ----------
        frames: int
            The number of frames to stream; if 0, stream indefinitely.
        """
        # wait for kickoff to be set
        self._fly_start.wait()
        self.logger.debug("Starting streaming thread.")

        # regardless of whether its
        # a continous acquisition or not,
        # there is an unfortunate extra copy
        # to the internal ring buffer;
        # it would be spared if we could
        # access the camera image buffer directly
        frames_written = 0
        if frames > 0:
            while frames_written < frames:
                if self._fly_stop.is_set():
                    break
                self._wait_image_awailable()
                img = self._core.popNextImage()
                self._read_buffer.append(img)
                self._frame_sink.send(img)
                frames_written += 1
        else:
            # write until stopped
            while not self._fly_stop.is_set():
                self._wait_image_awailable()
                img = self._core.popNextImage()
                self._read_buffer.append(img)
                self._frame_sink.send(img)
                frames_written += 1
        self._writer.complete(self.name)
        self._complete_status.set_finished()

    def _wait_image_awailable(self) -> None:
        """Wait until an image is available in the core buffer.

        Wait for `timeout` seconds between polls to avoid busy waiting.
        It should correspond to the exposure time of the camera.

        Parameters
        ----------
        timeout: float
            The timeout in seconds between polls.
            Default is 0.001 seconds.
            The current exposure time is a good value to use here.
        """
        while self._core.getRemainingImageCount() < 1:
            # keep polling until an image is available;
            # just wait a bit to avoid busy waiting;
            time.sleep(self._current_exposure)
