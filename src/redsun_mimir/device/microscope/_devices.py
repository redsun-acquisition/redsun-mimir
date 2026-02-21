from __future__ import annotations

import time
from queue import Queue
from typing import TYPE_CHECKING

import numpy as np
import scipy.ndimage
from attrs import define, field, setters, validators
from bluesky.protocols import Descriptor
from microscope import ROI, AxisLimits
from microscope.simulators import SimulatedCamera, SimulatedLightSource, SimulatedStage
from sunflare.device import Device
from sunflare.engine import Status
from sunflare.log import Loggable
from sunflare.storage import StorageDescriptor

import redsun_mimir.device.utils as utils
from redsun_mimir.protocols import DetectorProtocol, LightProtocol, MotorProtocol
from redsun_mimir.utils.descriptors import (
    make_descriptor,
    make_key,
    make_reading,
)

if TYPE_CHECKING:
    from typing import Any, ClassVar, Iterator

    import numpy.typing as npt
    from bluesky.protocols import Reading, StreamAsset
    from bluesky.protocols import Descriptor, Location, Reading


# ---------------------------------------------------------------------------
# Module-level stage registry
# ---------------------------------------------------------------------------
# SimulatedStageDevice registers itself here by name on construction.
# SimulatedCameraDevice resolves its stage peer lazily on first trigger.
# This replaces the old Factory class without class-level globals or
# threading primitives.
_stage_registry: dict[str, "SimulatedStageDevice"] = {}


def _make_world_image(
    height: int,
    width: int,
    n_blobs: int = 40,
    rng: np.random.Generator | None = None,
) -> "npt.NDArray[np.uint16]":
    """Generate a synthetic grayscale world image with Gaussian blobs.

    The image is larger than the sensor so the stage can navigate over it.
    Blobs are placed at random positions with random amplitudes, giving a
    realistic-looking sparse fluorescence sample.

    Parameters
    ----------
    height, width:
        Dimensions of the world image in pixels.
    n_blobs:
        Number of Gaussian blobs to scatter across the image.
    rng:
        Optional seeded generator for reproducible output.

    Returns
    -------
    np.ndarray of dtype uint16, shape (height, width).
    """
    if rng is None:
        rng = np.random.default_rng()

    world = np.zeros((height, width), dtype=np.float64)
    sigma_range = (
        max(1, min(height, width) // 80),
        max(2, min(height, width) // 20),
    )
    xx, yy = np.meshgrid(np.arange(width), np.arange(height))
    for _ in range(n_blobs):
        cx = rng.integers(0, width)
        cy = rng.integers(0, height)
        sigma = float(rng.uniform(*sigma_range))
        amplitude = float(rng.uniform(0.3, 1.0))
        world += amplitude * np.exp(
            -((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * sigma**2)
        )

    world_max = world.max()
    if world_max > 0:
        world = world / world_max
    return (world * np.iinfo(np.uint16).max).astype(np.uint16)


@define(kw_only=True, init=False, eq=False)
class SimulatedStageDevice(Device, MotorProtocol, SimulatedStage, Loggable):  # type: ignore[misc]
    """Simulated stage device using the microscope library.

    Parameters
    ----------
    name : str
        Name of the device.
    egu : str
        Engineering units. Default is "mm".
    axis : list[str]
        Axis names.
    step_sizes : dict[str, float]
        Step sizes for each axis.
    limits : dict[str, tuple[float, float]]
        Position limits for each axis. Required for simulated stages.
    """

    name: str
    prefix: str = field(
        default="SIM",
        validator=validators.instance_of(str),
        metadata={"description": "Device class prefix for key generation."},
    )
    egu: str = field(
        default="mm",
        validator=validators.instance_of(str),
        on_setattr=setters.frozen,
        metadata={"description": "Engineering units."},
    )
    axis: list[str] = field(
        validator=validators.instance_of(list),
        on_setattr=setters.frozen,
        metadata={"description": "Axis names."},
    )
    step_sizes: dict[str, float] = field(
        validator=validators.instance_of(dict),
        metadata={"description": "Step sizes for each axis."},
    )
    limits: dict[str, tuple[float, float]] | None = field(
        default=None,
        converter=utils.convert_limits,
        metadata={"description": "Limits for each axis."},
    )

    def __init__(self, name: str, /, **kwargs: Any) -> None:
        super().__init__(name, **kwargs)
        self.__attrs_init__(name=name, **kwargs)

        if self.limits is None:
            raise ValueError(f"{self.__class__.__name__} requires limits to be set.")

        axis_limits = {
            ax: AxisLimits(lower=lim[0], upper=lim[1])
            for ax, lim in self.limits.items()
        }
        SimulatedStage.__init__(self, axis_limits)
        self._active_axis = self.axis[0]

        # Register in the module-level registry so cameras can resolve us by name.
        _stage_registry[name] = self

    def describe_configuration(self) -> dict[str, Descriptor]:
        descriptors: dict[str, Descriptor] = {
            make_key(self.name, "egu"): make_descriptor("settings", "string"),
            make_key(self.name, "axis"): make_descriptor(
                "settings", "array", shape=[len(self.axis)]
            ),
        }
        for ax in self.axis:
            key = make_key(self.name, f"step_size-{ax}")
            if self.limits is not None and ax in self.limits:
                low, high = self.limits[ax]
                descriptors[key] = make_descriptor(
                    "settings", "number", low=low, high=high
                )
            else:
                descriptors[key] = make_descriptor("settings", "number")
        return descriptors

    def read_configuration(self) -> dict[str, Reading[Any]]:
        timestamp = time.time()
        config: dict[str, Reading[Any]] = {
            make_key(self.name, "egu"): make_reading(self.egu, timestamp),
            make_key(self.name, "axis"): make_reading(self.axis, timestamp),
        }
        for ax, step in self.step_sizes.items():
            config[make_key(self.name, f"step_size-{ax}")] = make_reading(
                step, timestamp
            )
        return config

    def set(self, value: Any, **kwargs: Any) -> Status:
        s = Status()

        propr = kwargs.get("prop", None)
        if propr is not None:
            self.logger.info("Setting property %s to %s.", propr, value)
            if propr == "axis" and isinstance(value, str):
                self._active_axis = value
                s.set_finished()
                return s
            elif propr == "step_size" and isinstance(value, int | float):
                self.step_sizes[self._active_axis] = value
                s.set_finished()
                return s
            else:
                s.set_exception(ValueError(f"Invalid property: {propr}"))
                return s
        else:
            if not isinstance(value, int | float):
                s.set_exception(ValueError("Value must be a float or int."))
                return s
        step_size = self.step_sizes[self._active_axis]
        new_position = step_size * np.round(value / step_size)
        self.move_to({self._active_axis: new_position})
        s.set_finished()
        return s

    def locate(self) -> Location[float]:
        return {
            "setpoint": self.position[self._active_axis],
            "readback": self.position[self._active_axis],
        }


@define(kw_only=True, init=False, eq=False)
class SimulatedLightDevice(Device, LightProtocol, SimulatedLightSource, Loggable):  # type: ignore[misc]
    """Simulated light source using the microscope library.

    Parameters
    ----------
    name : str
        Name of the device.
    binary : bool
        Binary mode operation. Not supported for simulated lights.
    wavelength : int
        Wavelength in nm.
    egu : str
        Engineering units. Default is "mW".
    intensity_range : tuple[int | float, ...]
        Intensity range (min, max).
    step_size : int
        Step size for the intensity.
    """

    name: str
    prefix: str = field(
        default="SIM",
        validator=validators.instance_of(str),
        metadata={"description": "Device class prefix for key generation."},
    )
    binary: bool = field(
        default=False,
        validator=validators.instance_of(bool),
        metadata={"description": "Binary mode operation."},
    )
    wavelength: int = field(
        default=0,
        validator=validators.instance_of(int),
        metadata={"description": "Wavelength in nm."},
    )
    egu: str = field(
        default="mW",
        validator=validators.instance_of(str),
        on_setattr=setters.frozen,
        metadata={"description": "Engineering units."},
    )
    intensity_range: tuple[int | float, ...] = field(
        default=None,
        converter=utils.convert_to_tuple,
        metadata={"description": "Intensity range (min, max)."},
    )
    step_size: int = field(
        default=1,
        validator=validators.instance_of(int),
        metadata={"description": "Step size for the intensity."},
    )

    def __init__(self, name: str, /, **kwargs: Any) -> None:
        super().__init__(name, **kwargs)
        self.__attrs_init__(name=name, **kwargs)

        if self.binary:
            raise AttributeError(
                f"{self.__class__.__name__} does not support binary light sources."
            )
        if self.intensity_range == (0, 0) or self.intensity_range == (0.0, 0.0):
            raise AttributeError(
                f"{self.__class__.__name__} requires intensity range to be set."
            )
        SimulatedLightSource.__init__(self)

    def describe(self) -> dict[str, Descriptor]:
        return {
            "intensity": {
                "source": self.name,
                "dtype": "number",
                "shape": [],
                "units": self.egu,
                "limits": {
                    "control": {
                        "low": self.intensity_range[0],
                        "high": self.intensity_range[1],
                    }
                },
            },
            "enabled": {
                "source": self.name,
                "dtype": "boolean",
                "shape": [],
            },
        }

    def read(self) -> dict[str, Reading[Any]]:
        return {
            "intensity": {
                "value": self.intensity,
                "timestamp": time.time(),
            },
            "enabled": {
                "value": self.get_is_on(),
                "timestamp": time.time(),
            },
        }

    def describe_configuration(self) -> dict[str, Descriptor]:
        return {
            make_key(self.name, "wavelength"): make_descriptor(
                "settings", "integer", units="nm"
            ),
            make_key(self.name, "binary"): make_descriptor("settings", "string"),
            make_key(self.name, "egu"): make_descriptor("settings", "string"),
            make_key(self.name, "intensity_range"): make_descriptor(
                "settings", "array", shape=[2]
            ),
            make_key(self.name, "step_size"): make_descriptor("settings", "integer"),
        }

    def read_configuration(self) -> dict[str, Reading[Any]]:
        timestamp = time.time()
        return {
            make_key(self.name, "wavelength"): make_reading(self.wavelength, timestamp),
            make_key(self.name, "binary"): make_reading(self.binary, timestamp),
            make_key(self.name, "egu"): make_reading(self.egu, timestamp),
            make_key(self.name, "intensity_range"): make_reading(
                list(self.intensity_range), timestamp
            ),
            make_key(self.name, "step_size"): make_reading(self.step_size, timestamp),
        }

    def trigger(self) -> Status:
        s = Status()
        self.enable() if not self.get_is_on() else self.disable()
        self.logger.debug(
            f"Toggled light source {not self.get_is_on()} -> {self.get_is_on()}"
        )
        s.set_finished()
        return s

    def set(self, value: Any, **kwargs: Any) -> Status:
        s = Status()
        propr = kwargs.get("prop", None)
        if propr is not None:
            err_msg = f"{self.__class__.__name__} does not support property setting."
            self.logger.error(err_msg)
            s.set_exception(RuntimeError(err_msg))
            return s
        else:
            if not isinstance(value, int | float):
                s.set_exception(ValueError("Value must be a float or int."))
                return s
        self.intensity = value

        # the actual power is set as a percentage of the intensity range
        self.power = (value - self.intensity_range[0]) / (
            self.intensity_range[1] - self.intensity_range[0]
        )
        s.set_finished()
        return s


# ---------------------------------------------------------------------------
# World-image scale factor
# ---------------------------------------------------------------------------
# Number of world-image pixels per stage unit.
# Default: world image is 4× sensor in each dimension, so the stage can
# navigate over a 2× radius around the centre before hitting the edges.
_WORLD_SCALE: int = 4


@define(kw_only=True, init=False, eq=False)
class SimulatedCameraDevice(Device, DetectorProtocol, SimulatedCamera, Loggable):  # type: ignore[misc]
    """Simulated camera that produces stage-aware images when paired with a stage.

    When ``stage_name`` is set to the name of a
    :class:`SimulatedStageDevice` that has already been constructed, each
    triggered image is a cropped sub-region of a procedurally-generated
    Gaussian-blob world image centred on the current stage X/Y position.
    The Z axis position is used to simulate defocus via a Gaussian blur: the
    image is sharpest at Z = 0 and blurs linearly with ``|Z|``.

    When ``stage_name`` is ``None`` (the default) or the named stage has not
    been registered yet, the camera falls back to the standard
    :class:`~microscope.simulators.SimulatedCamera` noise/gradient patterns.

    Parameters
    ----------
    name : str
        Name of the detector model.
    sensor_shape : tuple[int, int]
        Sensor dimensions as ``(width, height)`` in pixels.
    stage_name : str | None
        Name of the :class:`SimulatedStageDevice` to use for stage-aware
        imaging.  Must match the ``name`` parameter used when constructing
        the stage device.  If ``None``, stage-aware mode is disabled.
    world_scale : int
        World-image size multiplier relative to the sensor (default 4).
        A value of 4 means the world image is ``4 × sensor_shape``, giving
        the stage room to navigate across a region twice the sensor size in
        each direction from the centre.
    n_blobs : int
        Number of Gaussian blobs in the procedurally generated world image
        (default 40).
    """

    name: str
    prefix: str = field(
        default="SIM",
        validator=validators.instance_of(str),
        metadata={"description": "Device class prefix for key generation."},
    )
    sensor_shape: tuple[int, int] = field(
        default=(512, 512),
        converter=utils.convert_shape,
        metadata={"description": "Shape of the sensor (width, height)."},
    )
    stage_name: str | None = field(
        default=None,
        metadata={"description": "Name of the SimulatedStageDevice to track."},
    )
    world_scale: int = field(
        default=4,
        validator=validators.instance_of(int),
        metadata={"description": "World-image size multiplier relative to sensor."},
    )
    n_blobs: int = field(
        default=40,
        validator=validators.instance_of(int),
        metadata={"description": "Number of Gaussian blobs in the world image."},
    )

    storage = StorageDescriptor()

    def __init__(self, name: str, /, **kwargs: Any) -> None:
        super().__init__(name, **kwargs)
        self.__attrs_init__(name=name, **kwargs)

        SimulatedCamera.__init__(self, sensor_shape=self.sensor_shape)
        self.initialize()

        self.roi = (0, 0, *self.sensor_shape)

        self._queue: Queue[tuple[npt.NDArray[Any], float]] = Queue()
        self.set_client(self._queue)

        # Key names for data collection
        self._buffer_key = make_key(self.name, "buffer")
        self._roi_key = make_key(self.name, "roi")
        self._buffer_stream_key = f"{self.name}:buffer:stream"

        self._complete_status = Status()
        self._assets_collected: bool = False

        # Stage reference — resolved lazily from the registry on first trigger.
        self._stage: SimulatedStageDevice | None = None

        # World image — generated once, lazily, when stage mode is first used.
        self._world_image: npt.NDArray[np.uint16] | None = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_stage(self) -> SimulatedStageDevice | None:
        """Return the stage device, resolving from the registry if needed."""
        if self._stage is not None:
            return self._stage
        if self.stage_name is None:
            return None
        stage = _stage_registry.get(self.stage_name)
        if stage is None:
            self.logger.warning(
                "Stage '%s' not found in registry; falling back to "
                "standard image generation. Has the stage been constructed?",
                self.stage_name,
            )
            return None
        required = {"x", "y", "z"}
        if not required.issubset(stage.axes.keys()):
            missing = required - stage.axes.keys()
            self.logger.warning(
                "Stage '%s' is missing axes %s; stage-aware mode requires "
                "x, y, and z. Falling back to standard image generation.",
                self.stage_name,
                missing,
            )
            return None
        self._stage = stage
        self.logger.info(
            "Resolved stage '%s' for stage-aware imaging.", self.stage_name
        )
        return self._stage

    def _get_world_image(self) -> npt.NDArray[np.uint16]:
        """Return the world image, generating it on first call."""
        if self._world_image is None:
            h = self.sensor_shape[1] * self.world_scale
            w = self.sensor_shape[0] * self.world_scale
            self._world_image = _make_world_image(h, w, n_blobs=self.n_blobs)
            self.logger.debug(
                "Generated world image (%d×%d) with %d blobs.",
                w,
                h,
                self.n_blobs,
            )
        return self._world_image

    def _fetch_data_stage_aware(
        self, stage: SimulatedStageDevice
    ) -> npt.NDArray[np.uint16]:
        """Produce a stage-position-dependent crop of the world image.

        The crop window is centred on the stage X/Y position (in world-image
        pixels).  Z position drives a Gaussian blur to simulate defocus.
        """
        world = self._get_world_image()
        world_h, world_w = world.shape
        sensor_w, sensor_h = self.sensor_shape

        # Map stage position to world-image coordinates.
        # Stage axes limits define the navigable extent; we map the full
        # limits range linearly onto the world image dimensions.
        x_limits = stage.axes["x"].limits
        y_limits = stage.axes["y"].limits
        x_pos = stage.position["x"]
        y_pos = stage.position["y"]
        z_pos = stage.position["z"]

        # Normalise position to [0, 1] within limits, then scale to world pixels.
        x_norm = (x_pos - x_limits.lower) / max(
            x_limits.upper - x_limits.lower, 1.0
        )
        y_norm = (y_pos - y_limits.lower) / max(
            y_limits.upper - y_limits.lower, 1.0
        )
        cx = int(x_norm * world_w)
        cy = int(y_norm * world_h)

        # Compute bounding box, clamped to world image edges.
        x0 = cx - sensor_w // 2
        y0 = cy - sensor_h // 2
        x1 = x0 + sensor_w
        y1 = y0 + sensor_h

        if x0 >= 0 and y0 >= 0 and x1 <= world_w and y1 <= world_h:
            crop = world[y0:y1, x0:x1].copy()
        else:
            # Pad with zeros when the sensor window extends beyond the world.
            crop = np.zeros((sensor_h, sensor_w), dtype=world.dtype)
            img_x0, img_x1 = max(0, x0), min(x1, world_w)
            img_y0, img_y1 = max(0, y0), min(y1, world_h)
            sub_x0 = max(-x0, 0)
            sub_y0 = max(-y0, 0)
            sub_x1 = sub_x0 + (img_x1 - img_x0)
            sub_y1 = sub_y0 + (img_y1 - img_y0)
            crop[sub_y0:sub_y1, sub_x0:sub_x1] = world[img_y0:img_y1, img_x0:img_x1]

        # Simulate defocus: Gaussian blur proportional to |Z|.
        z_limits = stage.axes["z"].limits
        z_range = max(z_limits.upper - z_limits.lower, 1.0)
        blur = abs(z_pos) / z_range * 10.0  # max ~10 px sigma at range edges
        if blur > 0.5:
            blurred = scipy.ndimage.gaussian_filter(crop.astype(np.float64), blur)
            crop = np.clip(blurred, 0, np.iinfo(np.uint16).max).astype(np.uint16)

        return crop

    # ------------------------------------------------------------------
    # SimulatedCamera override
    # ------------------------------------------------------------------

    def _fetch_data(self) -> npt.NDArray[Any] | None:
        """Override SimulatedCamera._fetch_data to add stage-awareness."""
        if not self._acquiring or self._triggered == 0:
            return None

        time.sleep(self._exposure_time)
        self._triggered -= 1

        stage = self._resolve_stage()
        if stage is not None:
            image = self._fetch_data_stage_aware(stage)
        else:
            # Fallback: standard SimulatedCamera image generation.
            dark = int(32 * np.random.rand())
            light = int(255 - 128 * np.random.rand())
            sensor_w, sensor_h = self.sensor_shape
            width = self._roi.width // self._binning.h
            height = self._roi.height // self._binning.v
            image = self._image_generator.get_image(
                width, height, dark, light, index=self._sent
            )

        self._sent += 1
        return image

    # ------------------------------------------------------------------
    # Bluesky protocol
    # ------------------------------------------------------------------

    def describe_configuration(self) -> dict[str, Descriptor]:
        """Describe the detector configuration."""
        config: dict[str, Descriptor] = {}
        for setting_name in self.get_all_settings():
            config[make_key(self.name, setting_name)] = make_descriptor(
                "settings", "string"
            )
        config[make_key(self.name, "sensor_shape")] = make_descriptor(
            "settings", "array", shape=[2]
        )
        if self.stage_name is not None:
            config[make_key(self.name, "stage_name")] = make_descriptor(
                "settings", "string", readonly=True
            )
        return config

    def read_configuration(self) -> dict[str, Reading[Any]]:
        """Read the detector configuration."""
        timestamp = time.time()
        config: dict[str, Reading[Any]] = {}
        for setting_name, setting_value in self.get_all_settings().items():
            config[make_key(self.name, setting_name)] = make_reading(
                setting_value, timestamp
            )
        config[make_key(self.name, "sensor_shape")] = make_reading(
            list(self.sensor_shape), timestamp
        )
        if self.stage_name is not None:
            config[make_key(self.name, "stage_name")] = make_reading(
                self.stage_name, timestamp
            )
        return config

    def set(self, value: Any, **kwargs: Any) -> Status:
        """Set detector parameters."""
        s = Status()
        try:
            prop = kwargs.get("prop", None)
            if prop is not None:
                if prop in self.get_all_settings():
                    self.set_setting(prop, value)
                    self.logger.debug(f"Set {prop} to {value} for {self.name}")
                else:
                    raise ValueError(f"Unknown property: {prop}")
            else:
                if isinstance(value, tuple) and len(value) == 4:
                    self.roi = value
                    roi_obj = ROI(
                        left=value[0], top=value[1], width=value[2], height=value[3]
                    )
                    self.set_roi(roi_obj)
                    self.logger.debug(f"Set ROI to {value} for {self.name}")
                else:
                    raise ValueError(
                        "Value must specify a property via 'prop' keyword "
                        "or be a 4-tuple for ROI"
                    )
            s.set_finished()
        except Exception as e:
            self.logger.error(
                f"Failed to set {kwargs.get('prop', 'ROI')} to {value}: {e}"
            )
            s.set_exception(e)
        return s

    def stage(self) -> Status:
        """Prepare the detector for acquisition."""
        s = Status()
        try:
            self.enable()
            self._do_enable()
            self.logger.debug(f"Staged {self.name}")
            s.set_finished()
        except Exception as e:
            self.logger.error(f"Failed to stage {self.name}: {e}")
            s.set_exception(e)
        return s

    def unstage(self) -> Status:
        """Stop the detector acquisition."""
        s = Status()
        try:
            self.disable()
            self.logger.debug(f"Unstaged {self.name}")
            s.set_finished()
        except Exception as e:
            self.logger.error(f"Failed to unstage {self.name}: {e}")
            s.set_exception(e)
        return s

    def kickoff(self) -> Status:
        """Kick off a continuous acquisition."""
        s = Status()
        try:
            self.logger.debug(f"Kicked off acquisition for {self.name}")
            s.set_finished()
        except Exception as e:
            self.logger.error(f"Failed to kickoff {self.name}: {e}")
            s.set_exception(e)
        return s

    def complete(self) -> Status:
        """Complete a continuous acquisition."""
        s = Status()
        try:
            self.logger.debug(f"Completed acquisition for {self.name}")
            s.set_finished()
        except Exception as e:
            self.logger.error(f"Failed to complete {self.name}: {e}")
            s.set_exception(e)
        return s

    def trigger(self) -> Status:
        """Trigger the detector to acquire an image."""
        s = Status()
        try:
            super().trigger()
            s.set_finished()
        except Exception as e:
            self.logger.error(f"Failed to trigger {self.name}: {e}")
            s.set_exception(e)
        return s

    def describe(self) -> dict[str, Descriptor]:
        """Describe a reading from the detector."""
        return {
            self._buffer_key: {
                "source": self.name,
                "dtype": "array",
                "shape": list(self.sensor_shape),
            },
            self._roi_key: {
                "source": self.name,
                "dtype": "array",
                "shape": [4],
            },
        }

    def read(self) -> dict[str, Reading[Any]]:
        """Read data from the detector."""
        timestamp: float
        data: npt.NDArray[Any]
        queue_item = self._queue.get()
        if len(queue_item) == 2:
            data, timestamp = queue_item
        else:
            data = queue_item  # type: ignore[unreachable]
            timestamp = time.time()
        return {
            self._buffer_key: {"value": data, "timestamp": timestamp},
            self._roi_key: {"value": self.roi, "timestamp": timestamp},
        }

    def prepare(self, value: dict[str, Any]) -> Status:
        """Prepare the detector for acquisition.

        Parameters
        ----------
        value : dict[str, Any]
            - capacity: int — max frames to store; 0 = unlimited.
        """
        s = Status()
        try:
            if self.storage is None:
                raise RuntimeError(
                    f"No storage backend configured for device '{self.name}'."
                )
            height, width = self.sensor_shape
            capacity = value.get("capacity", 0)
            self.storage.update_source(
                name=self.name,
                dtype=np.dtype("uint16"),
                shape=(height, width),
            )
            self._sink = self.storage.prepare(self.name, capacity)
            self._complete_status = Status()
            self._assets_collected = False
            s.set_finished()
        except Exception as e:
            s.set_exception(e)
        return s

    def describe_collect(self) -> dict[str, Descriptor]:
        """Describe the data collected during streaming acquisition."""
        height, width = self.sensor_shape
        return {
            self._buffer_stream_key: {
                "source": "data",
                "dtype": "array",
                "shape": [None, height, width],
                "external": "STREAM:",
            }
        }

    def collect_asset_docs(self, index: int | None = None) -> Iterator[StreamAsset]:
        """Collect stream asset documents after a completed acquisition."""
        if self.storage is None:
            return
        if not self._complete_status.done:
            return
        if self._assets_collected:
            return
        frames_written = self.storage.get_indices_written(self.name)
        if frames_written == 0:
            return
        frames_to_report = (
            min(index, frames_written) if index is not None else frames_written
        )
        self._assets_collected = True
        yield from self.storage.collect_stream_docs(self.name, frames_to_report)

    def get_index(self) -> int:
        """Return the number of frames written since last acquisition."""
        if self.storage is None:
            return 0
        return self.storage.get_indices_written(self.name)
