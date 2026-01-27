from __future__ import annotations

import threading as th
import time
import uuid
from typing import TYPE_CHECKING, TypedDict, cast

from acquire_zarr import (
    ArraySettings,
    DataType,
    Dimension,
    DimensionType,
    StreamSettings,
    ZarrStream,
)
from pymmcore_plus import CMMCorePlus as Core
from pymmcore_plus import DeviceType
from sunflare.engine import Status
from sunflare.log import Loggable

from redsun_mimir.model.utils import RingBuffer
from redsun_mimir.protocols import DetectorProtocol

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any, ClassVar, Iterator

    from bluesky.protocols import Descriptor, Reading, StreamAsset
    from event_model.documents import StreamDatum, StreamResource
    from typing_extensions import Unpack

    from ._config import MMCoreCameraModelInfo


class PrepareKwargs(TypedDict):
    capacity: int
    store_path: Path
    write_forever: bool


class MMCoreCameraModel(DetectorProtocol, Loggable):
    """Demo camera wrapper for CMMCorePlus.

    This class is a hack because it will fail initialization if
    a second camera object of the same class is created; this
    is because at this time MMCore does not support multiple
    instances of the same camera device.
    """

    # class variable to track initialization status;
    # multiple instances are not supported
    initialized: ClassVar[bool] = False

    # TODO: temporary helpers for development;
    # will need to be moved to the model info class,
    # and initialized at instance level rather than class level

    #: properties to expose in configuration/reading
    exposed_properties: ClassVar[set[str]] = {
        "Exposure",
        "DisplayImageNumber",
        "PixelType",
    }

    #: enumerated values per property
    enum_per_property: ClassVar[dict[str, set[str]]] = {
        "PixelType": {"8bit", "16bit", "32bit"},
    }

    #: mapping from pixel type to numpy dtype
    pixeltype_to_numpy: ClassVar[dict[str, str]] = {
        "8bit": "uint8",
        "16bit": "uint16",
        "32bit": "uint32",
    }
    np_to_zarr_dtype: ClassVar[dict[str, DataType]] = {
        "uint8": DataType.UINT8,
        "uint16": DataType.UINT16,
        "uint32": DataType.UINT32,
    }

    #: name of the pixel type property
    pixeltype_name: ClassVar[str] = "PixelType"

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
            self._core.initializeDevice(name)

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
        self._buffer_stream_key = f"{self.name}:buffer:stream"
        self._stream_settings = StreamSettings()
        self._array_settings: list[ArraySettings] = []
        self._fly_start = th.Event()
        self._fly_stop = th.Event()
        self._isflying = False
        self._current_exposure: float = 0.0
        self._frames_written = 0
        self._collection_counter = (
            0  # tracks frames already reported via collect_asset_docs
        )
        self._stream_resource_uid = (
            ""  # persistent UID for StreamResource across collection calls
        )
        self._describe_cache: dict[str, Descriptor] = {}  # cache describe results

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
            if key not in self.exposed_properties:
                continue

            choices: list[str] = []
            if key in self.enum_per_property:
                choices = list(self.enum_per_property[key])
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
            if maximum and minimum:
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
            if prop.name not in self.exposed_properties:
                continue

            config[f"{self.name}:{prop.name}"] = {
                "value": prop.value,
                "timestamp": timestamp,
            }
        return config

    def stage(self) -> Status:
        s = Status()

        # get current exposure time in seconds
        self._current_exposure = self._core.getExposure() / 1000.0
        try:
            self._core.setCameraDevice(self.name)
            self._core.startContinuousSequenceAcquisition()
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

    def prepare(self, **kwargs: Unpack[PrepareKwargs]) -> Status:
        """Prepare the detector for acquisition.

        Parameters
        ----------
        kwargs: PrepareKwargs
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
        try:
            width, height = self._core.getImageWidth(), self._core.getImageHeight()
            dtype = self.pixeltype_to_numpy[
                self._core.getProperty(self.name, self.pixeltype_name)
            ]
            zarr_dtype = self.np_to_zarr_dtype[dtype]
            capacity = kwargs.get("capacity", 0)
            store_path = str(kwargs.get("store_path"))
            write_forever = kwargs.get("write_forever")
            if write_forever:
                # override any previous setting
                capacity = 0  # unlimited
            t = Dimension(
                name="t",
                kind=DimensionType.TIME,
                array_size_px=capacity,
                chunk_size_px=1,
                shard_size_chunks=2,
            )
            y = Dimension(
                name="y",
                kind=DimensionType.SPACE,
                array_size_px=height,
                chunk_size_px=height // 4,
                shard_size_chunks=2,
            )
            x = Dimension(
                name="x",
                kind=DimensionType.SPACE,
                array_size_px=width,
                chunk_size_px=width // 4,
                shard_size_chunks=2,
            )
            self._array_settings = [
                ArraySettings(
                    dimensions=[t, y, x], data_type=zarr_dtype, output_key=self.name
                )
            ]

            # create 1 frame ring buffer to
            # allow reading to continue while streaming
            self._read_buffer = RingBuffer(
                max_capacity=1, dtype=(dtype, (height, width))
            )

            self._stream_settings.store_path = store_path
            self._stream_settings.arrays = self._array_settings
            self._stream = ZarrStream(self._stream_settings)
            self._thread = th.Thread(
                target=self._stream_to_disk,
                kwargs={
                    "frames": capacity,
                },
            )
            self._thread.start()
            # Reset collection state for new acquisition
            self._collection_counter = 0
            self._stream_resource_uid = str(uuid.uuid4())
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
            # reset the frame counter and
            # start the background thread
            self._frames_written = 0
            self._fly_start.set()
            self._isflying = True
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
        s = Status()
        if not self._isflying:
            s.set_exception(
                RuntimeError("Not flying; kickoff() must be called first. ")
            )
            return s
        self._fly_stop.set()
        self._thread.join()
        # thread is joined; clear both
        # events and close the stream
        self._fly_start.clear()
        self._fly_stop.clear()
        self._isflying = False
        self._stream.close()
        s.set_finished()
        return s

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
        if not self._isflying:
            self._wait_image_awailable(timeout=self._current_exposure)
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
        # Return cached result if available
        if self._describe_cache:
            return self._describe_cache

        # Base description without stream assets (for live reads)
        result: dict[str, Descriptor] = {
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

        self._describe_cache = result
        return result

    def describe_collect(self) -> dict[str, Descriptor]:
        """Describe the data collected during acquisition.

        Provides an overview of the final assets stored
        on disk after flyer acquisition is complete.

        Returns
        -------
        dict[str, Descriptor]
            A dictionary describing the collected data.
        """
        return {
            self._buffer_stream_key: {
                "source": "data",
                "dtype": "array",
                "shape": [None, *self.roi[3:4]],
                "external": "STREAM:",
            }
        }

    def collect_asset_docs(self, index: int | None = None) -> Iterator[StreamAsset]:
        """Collect the assets stored on disk.

        This method is called by the RunEngine during backstop_collect when the run ends,
        or can be called explicitly via bps.collect().

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
        # Only emit asset docs if we actually wrote frames to disk AND we're not currently flying
        # This prevents emitting assets during read_while_waiting (while streaming is active)
        # Assets should only be emitted after complete() is called
        if self._frames_written == 0 or self._isflying:
            return

        # Determine how many frames to report
        if index is not None:
            frames_to_report = min(index, self._frames_written)
        else:
            frames_to_report = self._frames_written

        # If we've already reported all frames, don't emit anything
        if self._collection_counter >= frames_to_report:
            return

        # Only emit StreamResource on first call (when counter is 0)
        if self._collection_counter == 0:
            stream_resource: StreamResource = {
                "data_key": self._buffer_stream_key,
                "mimetype": "application/acquire-zarr",
                "parameters": {},  # TODO: add parameters if needed
                "uid": self._stream_resource_uid,
                "uri": self._stream_settings.store_path,
            }
            yield ("stream_resource", stream_resource)

        # Always emit StreamDatum with incremental indices
        stream_datum: StreamDatum = {
            "descriptor": "",  # RunEngine fills this in
            "indices": {"start": self._collection_counter, "stop": frames_to_report},
            "seq_nums": {"start": 0, "stop": 0},  # RunEngine fills this in
            "stream_resource": self._stream_resource_uid,
            "uid": f"{self._stream_resource_uid}/{self._collection_counter}",
        }
        yield ("stream_datum", stream_datum)

        # Update counter to track how many frames we've reported
        self._collection_counter = frames_to_report

    def get_index(self) -> int:
        """Return the number of frames written since last flight."""
        return self._frames_written

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
        if frames > 0:
            while self._frames_written < frames:
                if self._fly_stop.is_set():
                    break
                self._wait_image_awailable(timeout=self._current_exposure)
                img = self._core.popNextImage()
                self._read_buffer.append(img)
                self._stream.append(img)
                self._frames_written += 1
        else:
            # write until stopped
            while not self._fly_stop.is_set():
                self._wait_image_awailable(timeout=self._current_exposure)
                img = self._core.popNextImage()
                self._read_buffer.append(img)
                self._stream.append(img)
                self._frames_written += 1

        self.logger.debug("Streaming concluded.")

    def _wait_image_awailable(self, *, timeout: float = 0.001) -> None:
        """Wait until an image is available in the core buffer.

        Wait for `timeout` seconds between polls to avoid busy waiting.
        It should correspond to the exposure time of the camera.

        Parameters
        ----------
        timeout: float
            The timeout in seconds between polls.
            Default is 0.001 seconds.
            The current exposure time is be a good value to use here.
        """
        while self._core.getRemainingImageCount() == 0:
            # keep polling until an image is available;
            # just wait a bit to avoid busy waiting;
            time.sleep(timeout)
