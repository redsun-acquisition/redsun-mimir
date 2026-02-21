from __future__ import annotations

import time
from collections import defaultdict
from queue import Queue
from typing import TYPE_CHECKING

import numpy as np
import scipy.ndimage
from attrs import define, field, setters, validators
from bluesky.protocols import Descriptor
from microscope import ROI, AxisLimits
from microscope.simulators import SimulatedCamera, SimulatedLightSource, SimulatedStage
from microscope.simulators.stage_aware_camera import StageAwareCamera
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
    from collections.abc import Callable
    from typing import Any, Iterator

    import numpy.typing as npt
    from bluesky.protocols import Descriptor, Location, Reading, StreamAsset


# ---------------------------------------------------------------------------
# Stage callback registry
# ---------------------------------------------------------------------------
# Order-independent wiring between SimulatedStageDevice and SimulatedCameraDevice.
#
# Protocol:
#   1. SimulatedCameraDevice.__init__ registers a callback keyed by stage_name:
#        _stage_callbacks[stage_name].append(camera._on_stage_ready)
#   2. SimulatedStageDevice.__init__ fires all pending callbacks for its name:
#        for cb in _stage_callbacks.pop(name, []): cb(self)
#
# Declaration order in the container does not matter:
#   - Stage built first  → callback list is empty, nothing to do; cameras that
#     arrive later find the stage already in _stage_registry and call
#     _on_stage_ready immediately in their own __init__.
#   - Camera built first → callback is queued; fires when the stage arrives.
#
# _stage_registry keeps a reference so cameras built *after* the stage can
# still wire up without needing to re-register a callback.

_stage_registry: dict[str, SimulatedStageDevice] = {}
_stage_callbacks: dict[str, list[Callable[[SimulatedStageDevice], None]]] = defaultdict(list)


# ---------------------------------------------------------------------------
# Procedural world-image generator
# ---------------------------------------------------------------------------

def _make_world_image(
    height: int,
    width: int,
    n_blobs: int = 40,
    rng: np.random.Generator | None = None,
) -> npt.NDArray[np.uint16]:
    """Generate a synthetic single-channel world image populated with Gaussian blobs.

    Returns a ``uint16`` array of shape ``(height, width, 1)`` — the trailing
    channel axis is required by :class:`~microscope.simulators.stage_aware_camera.StageAwareCamera`.

    Parameters
    ----------
    height, width:
        Dimensions of the world image in pixels.
    n_blobs:
        Number of Gaussian blobs to scatter across the image.
    rng:
        Optional seeded :class:`numpy.random.Generator` for reproducibility.
    """
    if rng is None:
        rng = np.random.default_rng()

    world = np.zeros((height, width), dtype=np.float64)
    sigma_lo = max(1, min(height, width) // 80)
    sigma_hi = max(2, min(height, width) // 20)

    xx, yy = np.meshgrid(np.arange(width), np.arange(height))
    for _ in range(n_blobs):
        cx = rng.integers(0, width)
        cy = rng.integers(0, height)
        sigma = float(rng.uniform(sigma_lo, sigma_hi))
        amplitude = float(rng.uniform(0.3, 1.0))
        world += amplitude * np.exp(
            -((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * sigma**2)
        )

    world_max = world.max()
    if world_max > 0:
        world /= world_max
    # Add trailing channel axis (shape: H x W x 1)
    return (world * np.iinfo(np.uint16).max).astype(np.uint16)[:, :, np.newaxis]


# ---------------------------------------------------------------------------
# Minimal single-position FilterWheel stub
# ---------------------------------------------------------------------------
# StageAwareCamera requires a FilterWheel to select image channels.
# Since our world image is always single-channel (grayscale), we supply a
# trivial stub that satisfies the ABC without any real hardware machinery.
# This is intentionally package-private — nothing outside this module needs
# to know it exists.

class _SingleChannelFilterWheel(microscope.abc.FilterWheel if False else object):
    """Stub filterwheel with exactly one position, satisfying StageAwareCamera."""

    _positions: int = 1

    @property
    def n_positions(self) -> int:
        return 1

    @property
    def position(self) -> int:
        return 0

    def _do_get_position(self) -> int:
        return 0

    def _do_set_position(self, position: int) -> None:
        pass

    def _do_shutdown(self) -> None:
        pass


import microscope.abc as _abc  # noqa: E402

class _SingleChannelFilterWheel(_abc.FilterWheel):  # type: ignore[no-redef]
    """Stub filterwheel with exactly one position, satisfying StageAwareCamera."""

    def __init__(self) -> None:
        # Bypass Device.__init__ — we only need the FilterWheel interface,
        # not any real device lifecycle management.
        self._positions = 1

    @property
    def position(self) -> int:
        return 0

    def _do_get_position(self) -> int:
        return 0

    def _do_set_position(self, position: int) -> None:
        pass

    def _do_shutdown(self) -> None:
        pass


# ---------------------------------------------------------------------------
# SimulatedStageDevice
# ---------------------------------------------------------------------------


@define(kw_only=True, init=False, eq=False)
class SimulatedStageDevice(Device, MotorProtocol, SimulatedStage, Loggable):  # type: ignore[misc]
    """Simulated stage device using the microscope library.

    Parameters
    ----------
    name : str
        Name of the device.
    egu : str
        Engineering units.  Default ``"mm"``.
    axis : list[str]
        Axis names.
    step_sizes : dict[str, float]
        Step sizes for each axis.
    limits : dict[str, tuple[float, float]]
        Position limits for each axis.  Required for simulated stages.
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

        # Register in the stage registry so late-arriving cameras can find us.
        _stage_registry[name] = self

        # Fire any callbacks that cameras registered before we were built.
        for cb in _stage_callbacks.pop(name, []):
            cb(self)
            self.logger.debug(
                "Fired pending stage callback for '%s'.", name
            )

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


# ---------------------------------------------------------------------------
# SimulatedLightDevice
# ---------------------------------------------------------------------------


@define(kw_only=True, init=False, eq=False)
class SimulatedLightDevice(Device, LightProtocol, SimulatedLightSource, Loggable):  # type: ignore[misc]
    """Simulated light source using the microscope library.

    Parameters
    ----------
    name : str
        Name of the device.
    binary : bool
        Binary mode operation.  Not supported for simulated lights.
    wavelength : int
        Wavelength in nm.
    egu : str
        Engineering units.  Default ``"mW"``.
    intensity_range : tuple[int | float, ...]
        Intensity range ``(min, max)``.
    step_size : int
        Step size for intensity control.
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
        if self.intensity_range in ((0, 0), (0.0, 0.0)):
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
            "Toggled light source %s -> %s", not self.get_is_on(), self.get_is_on()
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
        if not isinstance(value, int | float):
            s.set_exception(ValueError("Value must be a float or int."))
            return s
        self.intensity = value
        self.power = (value - self.intensity_range[0]) / (
            self.intensity_range[1] - self.intensity_range[0]
        )
        s.set_finished()
        return s


# ---------------------------------------------------------------------------
# SimulatedCameraDevice
# ---------------------------------------------------------------------------


@define(kw_only=True, init=False, eq=False)
class SimulatedCameraDevice(Device, DetectorProtocol, StageAwareCamera, Loggable):  # type: ignore[misc]
    """Simulated camera that returns stage-position-dependent sub-regions of a
    procedurally generated world image.

    Inherits from
    :class:`~microscope.simulators.stage_aware_camera.StageAwareCamera`, which
    handles all the crop-and-defocus logic given a
    :class:`~microscope.abc.Stage`.  The stage is provided by a
    :class:`SimulatedStageDevice` sibling, wired via an order-independent
    callback mechanism: whichever of the two is constructed first sets up the
    link, so declaration order in the container does not matter.

    If ``read()`` is called before a stage has been registered (e.g. the stage
    was never configured), the camera returns a plain black frame at the
    correct sensor shape rather than raising.

    Parameters
    ----------
    name : str
        Name of the detector.
    sensor_shape : tuple[int, int]
        Sensor dimensions as ``(width, height)`` in pixels.
    stage_name : str | None
        Name of the :class:`SimulatedStageDevice` child to link to.
        ``None`` disables stage-aware imaging; the camera will always return
        blank frames from ``_fetch_data`` (which is unreachable in normal use
        since ``StageAwareCamera._fetch_data`` requires a stage).
    world_scale : int
        World-image size multiplier relative to the sensor (default ``4``).
    n_blobs : int
        Gaussian blobs in the procedural world image (default ``40``).
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
        metadata={"description": "Name of the SimulatedStageDevice child to link."},
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

        # Build the world image (H x W x 1, single channel for the stub filterwheel).
        w = self.sensor_shape[0] * self.world_scale
        h = self.sensor_shape[1] * self.world_scale
        world_image = _make_world_image(h, w, n_blobs=self.n_blobs)

        # The filterwheel stub satisfies StageAwareCamera's interface check
        # (image.shape[2] == filterwheel.n_positions == 1).
        self._filterwheel_stub = _SingleChannelFilterWheel()

        # We cannot call StageAwareCamera.__init__ yet because we may not have
        # a stage. Initialise SimulatedCamera (the grandparent) instead and
        # store the world image for later.  StageAwareCamera.__init__ is
        # called inside _on_stage_ready once the stage arrives.
        SimulatedCamera.__init__(self, sensor_shape=self.sensor_shape)
        self.initialize()
        self.roi = (0, 0, *self.sensor_shape)

        self._world_image = world_image
        self._stage_linked: bool = False

        self._queue: Queue[tuple[npt.NDArray[Any], float]] = Queue()
        self.set_client(self._queue)

        self._buffer_key = make_key(self.name, "buffer")
        self._roi_key = make_key(self.name, "roi")
        self._buffer_stream_key = f"{self.name}:buffer:stream"

        self._complete_status = Status()
        self._assets_collected: bool = False

        # Wire to stage — order-independent via callback registry.
        if self.stage_name is not None:
            if self.stage_name in _stage_registry:
                # Stage already built: link immediately.
                self._on_stage_ready(_stage_registry[self.stage_name])
            else:
                # Stage not built yet: register callback for when it arrives.
                _stage_callbacks[self.stage_name].append(self._on_stage_ready)
                self.logger.debug(
                    "Stage '%s' not yet built; registered callback.", self.stage_name
                )

    def _on_stage_ready(self, stage: SimulatedStageDevice) -> None:
        """Called (once) when the linked SimulatedStageDevice is constructed.

        Completes the StageAwareCamera initialisation now that we have both
        the world image and a concrete stage reference.  Safe to call from
        either thread (camera or stage construction happens on the main thread
        in normal container use).
        """
        required = {"x", "y", "z"}
        missing = required - stage.axes.keys()
        if missing:
            self.logger.warning(
                "Stage '%s' is missing axes %s; stage-aware mode requires "
                "x, y and z.  Camera will return blank frames.",
                self.stage_name,
                missing,
            )
            return

        # Finish StageAwareCamera initialisation: sets self._image, self._stage,
        # self._filterwheel, self._pixel_size, and replaces self._settings.
        StageAwareCamera.__init__(
            self,
            image=self._world_image,
            stage=stage,
            filterwheel=self._filterwheel_stub,
            sensor_shape=self.sensor_shape,
        )
        self._stage_linked = True
        self.logger.info(
            "Stage '%s' linked; stage-aware imaging active.", self.stage_name
        )

    # ------------------------------------------------------------------
    # _fetch_data fallback when no stage is linked yet
    # ------------------------------------------------------------------

    def _fetch_data(self) -> npt.NDArray[Any] | None:  # type: ignore[override]
        """Return None (no data) when no stage is linked.

        Once _on_stage_ready has run, StageAwareCamera._fetch_data takes over
        via normal MRO — this override is only reached when stage_name is None
        or the stage has not registered itself yet.
        """
        if self._stage_linked:
            return StageAwareCamera._fetch_data(self)

        # No stage yet: behave like a camera with nothing to acquire.
        if not self._acquiring or self._triggered == 0:
            return None
        self._triggered -= 1
        self._sent += 1
        self.logger.debug(
            "Stage not linked; returning blank frame for %s.", self.name
        )
        w = self._roi.width // self._binning.h
        h = self._roi.height // self._binning.v
        return np.zeros((h, w), dtype=np.uint16)

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
                    self.logger.debug("Set %s to %s for %s", prop, value, self.name)
                else:
                    raise ValueError(f"Unknown property: {prop}")
            elif isinstance(value, tuple) and len(value) == 4:
                self.roi = value
                self.set_roi(
                    ROI(left=value[0], top=value[1], width=value[2], height=value[3])
                )
                self.logger.debug("Set ROI to %s for %s", value, self.name)
            else:
                raise ValueError(
                    "Value must specify a property via 'prop' keyword "
                    "or be a 4-tuple for ROI"
                )
            s.set_finished()
        except Exception as e:
            self.logger.error(
                "Failed to set %s to %s: %s", kwargs.get("prop", "ROI"), value, e
            )
            s.set_exception(e)
        return s

    def stage(self) -> Status:  # type: ignore[override]
        """Prepare the detector for acquisition."""
        s = Status()
        try:
            self.enable()
            self._do_enable()
            self.logger.debug("Staged %s", self.name)
            s.set_finished()
        except Exception as e:
            self.logger.error("Failed to stage %s: %s", self.name, e)
            s.set_exception(e)
        return s

    def unstage(self) -> Status:
        """Stop the detector acquisition."""
        s = Status()
        try:
            self.disable()
            self.logger.debug("Unstaged %s", self.name)
            s.set_finished()
        except Exception as e:
            self.logger.error("Failed to unstage %s: %s", self.name, e)
            s.set_exception(e)
        return s

    def kickoff(self) -> Status:
        """Kick off a continuous acquisition."""
        s = Status()
        try:
            self.logger.debug("Kicked off acquisition for %s", self.name)
            s.set_finished()
        except Exception as e:
            self.logger.error("Failed to kickoff %s: %s", self.name, e)
            s.set_exception(e)
        return s

    def complete(self) -> Status:
        """Complete a continuous acquisition."""
        s = Status()
        try:
            self.logger.debug("Completed acquisition for %s", self.name)
            s.set_finished()
        except Exception as e:
            self.logger.error("Failed to complete %s: %s", self.name, e)
            s.set_exception(e)
        return s

    def trigger(self) -> Status:
        """Trigger the detector to acquire an image."""
        s = Status()
        try:
            super().trigger()
            s.set_finished()
        except Exception as e:
            self.logger.error("Failed to trigger %s: %s", self.name, e)
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
            Accepted keys: ``capacity`` (int, default 0 = unlimited).
        """
        s = Status()
        try:
            if self.storage is None:
                raise RuntimeError(
                    f"No storage backend configured for device '{self.name}'."
                )
            height, width = self.sensor_shape
            self.storage.update_source(
                name=self.name,
                dtype=np.dtype("uint16"),
                shape=(height, width),
            )
            self._sink = self.storage.prepare(self.name, value.get("capacity", 0))
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
        if self.storage is None or not self._complete_status.done:
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
