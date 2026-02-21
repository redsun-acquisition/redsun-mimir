from __future__ import annotations

import time
from collections import defaultdict
from queue import Queue
from typing import TYPE_CHECKING, cast

import numpy as np
import scipy.ndimage
from attrs import define, field, setters, validators
from bluesky.protocols import Descriptor
from microscope import ROI, AxisLimits
from microscope.abc import FilterWheel as _FilterWheel
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
#   - Stage built first  -> callback list is empty; cameras that arrive later
#     find the stage in _stage_registry and call _on_stage_ready immediately.
#   - Camera built first -> callback is queued; fires when the stage arrives.
#
# _stage_registry keeps a reference so cameras built after the stage can wire
# up without re-registering a callback.

_stage_registry: dict[str, "SimulatedStageDevice"] = {}
_stage_callbacks: dict[str, list["Callable[[SimulatedStageDevice], None]"]] = (
    defaultdict(list)
)


# ---------------------------------------------------------------------------
# Procedural world-image generator
# ---------------------------------------------------------------------------


def _make_world_image(
    height: int,
    width: int,
    n_blobs: int = 40,
    rng: "np.random.Generator | None" = None,
) -> "npt.NDArray[np.uint16]":
    """Generate a synthetic single-channel world image populated with Gaussian blobs.

    Returns a ``uint16`` array of shape ``(height, width, 1)`` — the trailing
    channel axis is required by ``StageAwareCamera``.

    Parameters
    ----------
    height, width:
        Dimensions of the world image in pixels.
    n_blobs:
        Number of Gaussian blobs to scatter across the image.
    rng:
        Optional seeded generator for reproducibility.
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
    return (world * np.iinfo(np.uint16).max).astype(np.uint16)[:, :, np.newaxis]


# ---------------------------------------------------------------------------
# Minimal single-position FilterWheel stub
# ---------------------------------------------------------------------------
# StageAwareCamera requires a FilterWheel only to read filterwheel.position
# as a channel index.  Since our world image is always single-channel we use
# a trivial stub with n_positions=1 / position=0.  It bypasses Device.__init__
# and is package-private — nothing outside this module needs it.


class _SingleChannelFilterWheel(_FilterWheel):  # type: ignore[misc]
    """Stub filterwheel with exactly one position, satisfying ``StageAwareCamera``."""

    def __init__(self) -> None:
        # Bypass Device.__init__ — we only need the FilterWheel interface.
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
    name:
        Name of the device.
    egu:
        Engineering units.  Default ``"mm"``.
    axis:
        Axis names.
    step_sizes:
        Step sizes for each axis.
    limits:
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

    def __init__(self, name: str, /, **kwargs: "Any") -> None:
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

        # Register so late-arriving cameras can find us.
        _stage_registry[name] = self

        # Fire callbacks queued by cameras that were built before us.
        for cb in _stage_callbacks.pop(name, []):
            cb(self)
            self.logger.debug("Fired pending stage callback for '%s'.", name)

    def describe_configuration(self) -> "dict[str, Descriptor]":
        """Describe the stage configuration."""
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

    def read_configuration(self) -> "dict[str, Reading[Any]]":
        """Read the stage configuration."""
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

    def set(self, value: "Any", **kwargs: "Any") -> Status:
        """Move the stage or update a configuration property.

        Parameters
        ----------
        value:
            Target position, or the new value for the property specified by
            ``prop``.
        **kwargs:
            ``prop="axis"`` switches the active axis (``value`` must be a
            ``str`` axis name). ``prop="step_size"`` updates the step size
            for the current axis (``value`` must be numeric).
        """
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

    def locate(self) -> "Location[float]":
        """Return the current setpoint and readback for the active axis."""
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
    name:
        Name of the device.
    binary:
        Binary mode operation.  Not supported; always raises if ``True``.
    wavelength:
        Wavelength in nm.
    egu:
        Engineering units.  Default ``"mW"``.
    intensity_range:
        Intensity range as ``(min, max)``.
    step_size:
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

    def __init__(self, name: str, /, **kwargs: "Any") -> None:
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
        self.intensity: float = float(self.intensity_range[0])

    def describe(self) -> "dict[str, Descriptor]":
        """Describe the data produced by the light source."""
        return {
            make_key(self.name, "intensity"): {
                "source": "data",
                "dtype": "number",
                "shape": [],
            },
            make_key(self.name, "enabled"): {
                "source": "data",
                "dtype": "boolean",
                "shape": [],
            },
        }

    def read(self) -> "dict[str, Reading[Any]]":
        """Read the current intensity and enabled state."""
        ts = time.time()
        return {
            make_key(self.name, "intensity"): make_reading(self.intensity, ts),
            make_key(self.name, "enabled"): make_reading(self.get_is_on(), ts),
        }

    def describe_configuration(self) -> "dict[str, Descriptor]":
        """Describe the light source configuration."""
        return {
            make_key(self.name, "wavelength"): make_descriptor(
                "settings", "integer", units="nm", readonly=True
            ),
            make_key(self.name, "binary"): make_descriptor(
                "settings", "string", readonly=True
            ),
            make_key(self.name, "egu"): make_descriptor(
                "settings", "string", readonly=True
            ),
            make_key(self.name, "intensity_range"): make_descriptor(
                "settings", "array", shape=[2], readonly=True
            ),
            make_key(self.name, "step_size"): make_descriptor(
                "settings", "integer", readonly=True
            ),
        }

    def read_configuration(self) -> "dict[str, Reading[Any]]":
        """Read the light source configuration."""
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
        """Toggle the light source on or off."""
        s = Status()
        self.enable() if not self.get_is_on() else self.disable()
        self.logger.debug(
            "Toggled light source %s -> %s", not self.get_is_on(), self.get_is_on()
        )
        s.set_finished()
        return s

    def set(self, value: "Any", **kwargs: "Any") -> Status:
        """Set the intensity of the light source.

        Parameters
        ----------
        value:
            Target intensity value within ``intensity_range``.
        **kwargs:
            Property setting is not supported; passing ``prop`` raises an
            error.
        """
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
    """Simulated microscope camera with optional stage-aware imaging.

    Inherits from ``StageAwareCamera``, which handles XY cropping from stage
    position and Z-based Gaussian defocus.  The linked stage is provided by a
    ``SimulatedStageDevice`` sibling through an order-independent callback
    mechanism: whichever of the two is constructed first sets up the link, so
    declaration order in the container does not matter.

    When no stage has been linked yet, ``_fetch_data`` returns a blank
    ``uint16`` frame at the correct sensor shape rather than raising.

    Parameters
    ----------
    name:
        Name of the detector.
    sensor_shape:
        Sensor dimensions as ``(width, height)`` in pixels.
    stage_name:
        Name of the ``SimulatedStageDevice`` child to link to.  ``None``
        disables stage-aware imaging and the camera always returns blank frames.
    world_scale:
        World-image size multiplier relative to the sensor.  Default ``4``.
    n_blobs:
        Number of Gaussian blobs in the procedural world image.  Default ``40``.
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

    def __init__(self, name: str, /, **kwargs: "Any") -> None:
        super().__init__(name, **kwargs)
        self.__attrs_init__(name=name, **kwargs)

        w = self.sensor_shape[0] * self.world_scale
        h = self.sensor_shape[1] * self.world_scale
        world_image = _make_world_image(h, w, n_blobs=self.n_blobs)

        self._filterwheel_stub = _SingleChannelFilterWheel()

        # Call SimulatedCamera.__init__ (grandparent) to set up acquisition
        # machinery.  StageAwareCamera.__init__ is deferred to _on_stage_ready
        # so we can use it regardless of construction order.
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

        if self.stage_name is not None:
            if self.stage_name in _stage_registry:
                self._on_stage_ready(_stage_registry[self.stage_name])
            else:
                _stage_callbacks[self.stage_name].append(self._on_stage_ready)
                self.logger.debug(
                    "Stage '%s' not yet built; registered callback.", self.stage_name
                )

    def _on_stage_ready(self, stage: SimulatedStageDevice) -> None:
        """Complete the ``StageAwareCamera`` initialisation once the stage exists.

        Called immediately from ``__init__`` when the stage is already
        registered, or later as a callback fired by
        ``SimulatedStageDevice.__init__``.

        Parameters
        ----------
        stage:
            The ``SimulatedStageDevice`` that has just been constructed.
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

    def _fetch_data(self) -> "npt.NDArray[Any] | None":
        """Return a stage-aware image or a blank frame if no stage is linked.

        Delegates to ``StageAwareCamera._fetch_data`` when a stage has been
        linked via ``_on_stage_ready``.  Returns a blank ``uint16`` frame
        otherwise so callers never receive ``None`` from a triggered camera.
        """
        if self._stage_linked:
            return cast(
                "npt.NDArray[Any] | None", StageAwareCamera._fetch_data(self)
            )

        if not self._acquiring or self._triggered == 0:
            return None
        self._triggered -= 1
        self._sent += 1
        self.logger.debug("Stage not linked; returning blank frame for %s.", self.name)
        w = self._roi.width // self._binning.h
        h = self._roi.height // self._binning.v
        return np.zeros((h, w), dtype=np.uint16)

    # ------------------------------------------------------------------
    # Bluesky protocol
    # ------------------------------------------------------------------

    def describe_configuration(self) -> "dict[str, Descriptor]":
        """Describe the camera configuration."""
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

    def read_configuration(self) -> "dict[str, Reading[Any]]":
        """Read the camera configuration."""
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

    def set(self, value: "Any", **kwargs: "Any") -> Status:
        """Set camera parameters.

        Parameters
        ----------
        value:
            New setting value, or a 4-tuple ``(left, top, width, height)``
            to update the ROI when no ``prop`` is given.
        **kwargs:
            ``prop`` selects a named camera setting from
            ``get_all_settings()``.
        """
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

    def stage(self) -> Status:
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
        """Trigger the detector to acquire one image."""
        s = Status()
        try:
            super().trigger()
            s.set_finished()
        except Exception as e:
            self.logger.error("Failed to trigger %s: %s", self.name, e)
            s.set_exception(e)
        return s

    def describe(self) -> "dict[str, Descriptor]":
        """Describe the data produced by the detector."""
        return {
            self._buffer_key: {
                "source": "data",
                "dtype": "array",
                "shape": [1, *self.sensor_shape],
            },
            self._roi_key: {
                "source": "data",
                "dtype": "array",
                "shape": [4],
            },
        }

    def read(self) -> "dict[str, Reading[Any]]":
        """Read a triggered image from the detector."""
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

    def prepare(self, value: "dict[str, Any]") -> Status:
        """Prepare the detector for streaming acquisition.

        Parameters
        ----------
        value:
            ``capacity`` (``int``, default ``0``) — maximum number of frames
            to store; ``0`` means unlimited.
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

    def describe_collect(self) -> "dict[str, Descriptor]":
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

    def collect_asset_docs(
        self, index: "int | None" = None
    ) -> "Iterator[StreamAsset]":
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
        """Return the number of frames written since the last acquisition."""
        if self.storage is None:
            return 0
        return self.storage.get_indices_written(self.name)
