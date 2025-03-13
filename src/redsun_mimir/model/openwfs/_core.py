from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from threading import Event
from typing import TYPE_CHECKING, Literal

import astropy.units as u
import numpy as np
import numpy.typing as npt
from openwfs.core import Actuator, Detector, Processor
from openwfs.simulation import Camera, Microscope, XYStage

if TYPE_CHECKING:
    from typing import Any, Callable, Union

    import numpy.typing as npt
    from openwfs.core import Detector

    from .._config import Specimen

DeviceType = Literal["light", "camera", "xy_stage", "z_stage"]


class Intensity(Processor):  # type: ignore
    """Regulates the intensity of an incoming image.

    Emulates the behavior of a light source intensity control.
    The image incoming from a microscope is multiplied by
    a percentage factor (between 0 and 1) to simulate the
    intensity control.
    """

    def __init__(self, source: Union[Detector, npt.NDArray[Any]]):
        super().__init__(source, multi_threaded=False)
        self._intensity = 0.0
        self._open = False

    def _fetch(self, source: npt.NDArray[Any]) -> npt.NDArray[Any]:
        intensity = self.intensity if self.open else 0.0
        return source * intensity

    @property
    def open(self) -> bool:
        """The open status of the intensity control."""
        return self._open

    @open.setter
    def open(self, value: bool) -> None:
        self._open = value

    @property
    def intensity(self) -> float:
        """The intensity factor."""
        return self._intensity

    @intensity.setter
    def intensity(self, value: float) -> None:
        self._intensity = np.clip(value, 0, 1)


class Stage(Actuator):  # type: ignore
    """Mimics a single-axis stage actuator.

    Parameters
    ----------
    axis: ``str``
        The axis of the stage. Suggested usage is single characters (i.e. 'x', 'y', 'z').
    step_size: ``Quantity[u.um]``
        The step size of the stage along `axis` (in micrometers).

    """

    def __init__(self, axis: str, step_size: u.Quantity[u.um]):
        super().__init__(duration=0 * u.ms, latency=0 * u.ms)
        self._position = 0.0 * u.um
        self._axis = axis
        self._step_size = step_size.to(u.um)

    @property
    def axis(self) -> str:
        """The axis of the stage."""
        return self._axis

    @property
    def step_size(self) -> u.Quantity[u.um]:
        """The step size of the stage along the axis."""
        return self._step_size

    @step_size.setter
    def step_size(self, value: u.Quantity[u.um]) -> None:
        self._step_size = value

    @property
    def position(self) -> u.Quantity[u.um]:
        """The current position of the stage along the axis."""
        return self._position

    @position.setter
    def position(self, value: u.Quantity[u.um]) -> None:
        self._position = self.step_size * np.round(value.to(u.um) / self.step_size)


class MicroscopeFactory:
    def __init__(self) -> None:
        self._call_map: dict[str, Callable[..., Any]] = {
            "xy_stage": self._get_xy_stage,
            "z_stage": self._get_z_stage,
            "light": self._get_intensity,
            "camera": self._get_camera,
        }

        self.xy_stage_ready = Event()
        self.z_stage_ready = Event()
        self.microscope_ready = Event()
        self.shutter_ready = Event()
        self.light_ready = Event()
        self.executor = ThreadPoolExecutor(max_workers=4)

    def __call__(
        self,
        device_type: DeviceType,
        **kwargs: Any,
    ) -> Future[Any]:
        future = self.executor.submit(self._call_map[device_type], **kwargs)
        return future

    def _get_z_stage(self, step_z: float, *, egu_z: str = "um") -> Stage:
        step_size_z = u.Quantity(step_z, egu_z)
        self.z_stage = Stage("z", step_size_z)
        self.z_stage_ready.set()
        return self.z_stage

    def _get_xy_stage(
        self, step_x: float, step_y: float, *, egu_x: str = "um", egu_y: str = "um"
    ) -> XYStage:
        step_size_x = u.Quantity(step_x, egu_x)
        step_size_y = u.Quantity(step_y, egu_y)
        self.xy_stage = XYStage(step_size_x, step_size_y)
        self.xy_stage_ready.set()
        return self.xy_stage

    def _get_intensity(self) -> Intensity:
        self.microscope_ready.wait()
        self.light = Intensity(self.microscope)
        self.light_ready.set()
        return self.light

    def _build_microscope(self, specimen: Specimen) -> None:
        self.xy_stage_ready.wait()
        self.z_stage_ready.wait()
        source = np.random.randint(-10000, 100, specimen.resolution, dtype=np.int16)
        source = np.maximum(source, 0)
        wavelength = u.Quantity(specimen.wavelength, "nm")
        self.microscope = Microscope(
            source=source,
            numerical_aperture=specimen.numerical_aperture,
            wavelength=wavelength,
            magnification=specimen.magnification,
            xy_stage=self.xy_stage,
            z_stage=self.z_stage,
        )
        self.microscope_ready.set()

    def _get_camera(
        self, *, specimen: Specimen, digital_bits: int, sensor_shape: tuple[int, int]
    ) -> Camera:
        self._build_microscope(specimen)
        self.light_ready.wait()
        digital_max = 2**digital_bits - 1
        self.camera = Camera(
            self.light, digital_max=digital_max, shot_noise=True, shape=sensor_shape
        )
        return self.camera


Factory = MicroscopeFactory()

__all__ = ["Factory", "Intensity", "Stage", "XYStage", "Camera"]
