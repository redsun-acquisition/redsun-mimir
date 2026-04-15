"""MMCore camera device — ophyd-async ``StandardDetector`` wrapper."""

from __future__ import annotations

import asyncio
import threading as th
import time
from typing import TYPE_CHECKING, Generic, TypeVar

import numpy as np
from ophyd_async.core import (
    AsyncStatus,
    DetectorController,
    SignalR,
    StandardDetector,
    TriggerInfo,
    soft_signal_r_and_setter,
)
from pymmcore_plus import CMMCorePlus as Core
from redsun.log import Loggable
from redsun.storage import HasWriterLogic, SharedDetectorWriter
from redsun.utils.descriptors import make_descriptor, make_key, make_reading, parse_key

from redsun_mimir.device.mmcore.configs import (
    BaseCamConfig,
    DahengCamConfig,
    DemoCamConfig,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any, ClassVar, Literal

    import numpy.typing as npt
    from bluesky.protocols import Descriptor, Reading

WriterT = TypeVar("WriterT", bound=SharedDetectorWriter)


class MMCoreDetectorController(DetectorController, Generic[WriterT]):
    """MMCore detector controller, generic over the shared writer type.

    Handles arming, streaming, and disarming the MMCore camera.  Runs the
    blocking acquisition loop in a thread pool via ``asyncio.to_thread`` so
    the event loop stays responsive.

    ``WriterT`` is bounded to
    [`SharedDetectorWriter`][redsun.storage.SharedDetectorWriter] because the
    controller calls ``writer.register()`` and ``writer.write_frame()`` —
    methods that extend the ophyd-async ``DetectorWriter`` ABC.

    Parameters
    ----------
    core :
        Singleton ``CMMCorePlus`` instance.
    writer :
        Shared multi-source writer instance.
    device_name :
        Name used as the source key when calling ``writer.register()`` and
        ``writer.write_frame()``.
    set_buffer :
        Sync callable (from ``soft_signal_r_and_setter``) that updates the
        camera's ``buffer`` signal and notifies subscribers.
    """

    def __init__(
        self,
        core: Core,
        writer: WriterT,
        device_name: str,
        set_buffer: Callable[[npt.NDArray[Any]], None],
    ) -> None:
        self._core = core
        self._writer: WriterT = writer
        self._device_name = device_name
        self._set_buffer = set_buffer
        self._n_frames: int = 0
        self._current_exposure: float = 0.0
        self._stop_event = th.Event()
        self._stream_task: asyncio.Task[None] | None = None

    def get_deadtime(self, exposure: float | None) -> float:
        """Return controller deadtime (zero for MMCore software triggering)."""
        return 0.0

    async def prepare(self, trigger_info: TriggerInfo) -> None:
        """Register the acquisition source with the writer.

        Parameters
        ----------
        trigger_info :
            Plan-provided trigger parameters.  ``number_of_events`` determines
            the frame capacity (``0`` means unlimited / continuous).
        """
        n = trigger_info.number_of_events
        frames = sum(n) if isinstance(n, list) else n
        width = self._core.getImageWidth()
        height = self._core.getImageHeight()
        bpp = self._core.getBytesPerPixel()
        dtype = np.dtype(f"uint{bpp * 8}")
        self._writer.register(
            name=self._device_name,
            dtype=dtype,
            shape=(height, width),
            capacity=frames,
        )
        self._n_frames = frames
        exp_in_ms = self._core.getExposure()
        self._current_exposure = exp_in_ms / 1000.0

    async def arm(self) -> None:
        """Start the background streaming thread."""
        self._stop_event.clear()
        self._stream_task = asyncio.create_task(
            asyncio.to_thread(self._stream_sync, self._n_frames)
        )

    async def disarm(self) -> None:
        """Signal the streaming thread to stop and wait for it to finish."""
        self._stop_event.set()
        if self._stream_task is not None:
            await asyncio.shield(self._stream_task)
            self._stream_task = None

    async def wait_for_idle(self) -> None:
        """Await the streaming task completion."""
        if self._stream_task is not None:
            await self._stream_task

    def _stream_sync(self, frames: int) -> None:
        """Blocking acquisition loop — runs in executor thread.

        Parameters
        ----------
        frames :
            Number of frames to acquire.  ``0`` means stream indefinitely
            until ``disarm()`` sets the stop event.
        """
        if frames > 0:
            self._core.startSequenceAcquisition(frames, self._current_exposure, False)
        else:
            self._core.startContinuousSequenceAcquisition(self._current_exposure)

        frames_written = 0
        last_frame = 0
        try:
            while not self._stop_event.is_set():
                if self._core.getRemainingImageCount() > 0:
                    img, md = self._core.popNextImageAndMD()
                    last_frame = int(md.get("ImageNumber", frames_written))
                    self._set_buffer(img)
                    self._writer.write_frame(self._device_name, img)
                    frames_written += 1
                    if frames > 0 and frames_written >= frames:
                        break
                else:
                    time.sleep(self._current_exposure or 0.005)
        finally:
            try:
                self._core.stopSequenceAcquisition()
            except Exception:
                pass

        if frames > 0 and (last_frame + 1) > frames_written:
            import warnings

            warnings.warn(
                f"MMCoreDetectorController: lost {(last_frame + 1) - frames_written} frame(s).",
                stacklevel=1,
            )


class MMCoreCameraDevice(
    StandardDetector[MMCoreDetectorController[WriterT], WriterT],
    HasWriterLogic,
    Loggable,
    Generic[WriterT],
):
    """Camera wrapper for Micro-Manager Core.

    Inherits the full bluesky detector lifecycle from
    [`StandardDetector`][ophyd_async.core.StandardDetector] (``stage``,
    ``unstage``, ``prepare``, ``kickoff``, ``complete``,
    ``collect_asset_docs``) and adds MMCore hardware management.

    Parameters
    ----------
    name :
        Name of the device instance; used to register with the core.
    writer :
        Shared storage writer injected at construction time.  The controller
        calls ``writer.register()`` and ``writer.write_frame()`` during
        acquisition.  Exposed via
        [`writer_logic`][redsun_mimir.device.mmcore.MMCoreCameraDevice.writer_logic]
        for discovery by presenters through
        [`HasWriterLogic`][redsun.storage.HasWriterLogic].
    config :
        Configuration preset to use; determines the camera model and
        properties.
    """

    initialized: ClassVar[bool] = False

    buffer: SignalR[np.ndarray]

    def __init__(
        self,
        name: str,
        writer: WriterT,
        /,
        config: Literal["demo", "daheng"] = "demo",
    ) -> None:
        self.cam_config: BaseCamConfig
        match config:
            case "demo":
                self.cam_config = DemoCamConfig()
            case "daheng":
                self.cam_config = DahengCamConfig()
            case _:
                raise ValueError(
                    f"Unsupported config {config!r}; must be 'demo' or 'daheng'."
                )

        self._pixelprop = list(self.cam_config.numpy_dtype.keys())[0]
        self._core = Core.instance()

        try:
            if MMCoreCameraDevice.initialized:
                raise RuntimeError(
                    "MMCoreCameraDevice has already been initialized once; "
                    "multiple instances are not supported."
                )
            self._core.loadDevice(name, self.cam_config.adapter, self.cam_config.device)
            self._core.initializeDevice(name)
            self._core.setCameraDevice(name)
            MMCoreCameraDevice.initialized = True
        except Exception as e:
            raise e

        # Reset ROI to full frame on initialization.
        self._core.clearROI()
        self.sensor_shape: tuple[int, int] = self.cam_config.sensor_shape

        if self.cam_config.defaults:
            for prop, value in self.cam_config.defaults.items():
                if prop not in self.cam_config.properties:
                    continue
                self._core.setProperty(name, prop, value)

        self._core.setExposure(name, self.cam_config.starting_exposure)
        self.roi: tuple[int, int, int, int] = (0, 0, *self.sensor_shape)

        self._properties = {
            propr_name: self._core.getPropertyObject(name, propr_name)
            for propr_name in self.cam_config.properties
        }
        self._device_schema = self._core.getDeviceSchema(name)

        # Buffer signal — updated by the streaming thread via set_buffer().
        buf, set_buf = soft_signal_r_and_setter(
            np.ndarray,
            initial_value=np.zeros(
                (self.roi[3], self.roi[2]), dtype=np.dtype(self._get_dtype(name))
            ),
        )
        self.buffer = buf
        self._set_buf = set_buf

        ctrl: MMCoreDetectorController[WriterT] = MMCoreDetectorController(
            core=self._core,
            writer=writer,
            device_name=name,
            set_buffer=set_buf,
        )

        super().__init__(
            controller=ctrl,
            writer=writer,
            config_sigs=[],
            name=name,
        )
        self.logger.debug(
            f"Initialized {self.cam_config.adapter} -> {self.cam_config.device}"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_dtype(self, device_name: str) -> str:
        """Return the numpy dtype string for the current pixel type."""
        return self.cam_config.numpy_dtype[self._pixelprop][
            self._core.getProperty(device_name, self._pixelprop)
        ]

    @property
    def dtype(self) -> str:
        """The currently active pixel data type of the camera, as a numpy dtype string."""
        return self._get_dtype(self.name)

    # ------------------------------------------------------------------
    # HasWriterLogic
    # ------------------------------------------------------------------

    @property
    def writer_logic(self) -> WriterT:
        """Expose the injected writer for discovery via [`HasWriterLogic`][redsun.storage.HasWriterLogic]."""
        return self._writer

    # ------------------------------------------------------------------
    # Property setter
    # ------------------------------------------------------------------

    @AsyncStatus.wrap
    async def set(self, value: Any, **kwargs: Any) -> None:
        """Set a property of the detector.

        Parameters
        ----------
        value :
            The value to set for the property.
        **kwargs :
            Pass ``propr="<key>"`` to identify the target property.

        Raises
        ------
        ValueError
            If ``propr`` is not provided or the property is not found.
        """
        propr_raw: str | None = kwargs.get("propr", None)
        if not propr_raw:
            raise ValueError(
                "Property name must be specified via the 'propr' keyword argument."
            )
        _, propr = parse_key(propr_raw)

        if propr in self._properties:
            self._properties[propr].value = value
            # Refresh buffer shape/dtype in case pixel type changed.
            self._set_buf(
                np.zeros((self.roi[3], self.roi[2]), dtype=np.dtype(self.dtype))
            )
        elif propr == "exposure":
            self._core.setExposure(self.name, value)
        elif propr == "roi":
            self._core.setROI(self.name, *value)
            self.roi = tuple(value)
            self._set_buf(
                np.zeros((self.roi[3], self.roi[2]), dtype=np.dtype(self.dtype))
            )
        else:
            raise ValueError(f"Property {propr!r} not found.")

    # ------------------------------------------------------------------
    # Configuration describe / read
    # ------------------------------------------------------------------

    async def describe_configuration(self) -> dict[str, Descriptor]:
        """Describe all configurable properties of the detector."""
        config_descriptor: dict[str, Descriptor] = {}
        for prop_name, value in self._device_schema["properties"].items():
            if prop_name not in self.cam_config.properties:
                continue

            choices: list[str] = []
            if prop_name in self.cam_config.enum_map:
                choices = list(self.cam_config.enum_map[prop_name])
            elif value["type"] == "string":
                choices = value.get("enum", [])

            readonly = prop_name in self.cam_config.properties.readonly
            maximum: float | None = value.get("maximum", None)
            minimum: float | None = value.get("minimum", None)
            key = make_key(self.name, prop_name)

            if choices:
                config_descriptor[key] = make_descriptor(
                    "properties", "string", choices=choices, readonly=readonly
                )
            elif maximum is not None and minimum is not None:
                config_descriptor[key] = make_descriptor(
                    "properties", "number", low=minimum, high=maximum, readonly=readonly
                )
            else:
                config_descriptor[key] = make_descriptor(
                    "properties", "number", readonly=readonly
                )

        config_descriptor[make_key(self.name, "exposure")] = make_descriptor(
            "settings",
            "number",
            low=self.cam_config.exposure_limits[0],
            high=self.cam_config.exposure_limits[1],
            units="ms",
        )
        config_descriptor[make_key(self.name, "sensor_shape")] = make_descriptor(
            "settings", "array", shape=[2]
        )
        return config_descriptor

    async def read_configuration(self) -> dict[str, Reading[Any]]:
        """Read all configurable properties of the detector."""
        timestamp = time.time()
        config: dict[str, Reading[Any]] = {}

        for prop in self._properties.values():
            if prop.name not in self.cam_config.properties:
                continue
            config[make_key(self.name, prop.name)] = make_reading(prop.value, timestamp)

        config[make_key(self.name, "exposure")] = make_reading(
            self._core.getExposure(), timestamp
        )
        config[make_key(self.name, "sensor_shape")] = make_reading(
            list(self.sensor_shape), timestamp
        )
        return config
