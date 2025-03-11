from __future__ import annotations

from typing import TYPE_CHECKING

import astropy.units as u
import numpy as np
import numpy.typing as npt
from openwfs.core import Actuator, Detector, Processor
from openwfs.simulation import Camera, Microscope, Shutter, XYStage

if TYPE_CHECKING:
    from typing import Any, ClassVar, Optional, Union

    import numpy.typing as npt
    from openwfs.core import Detector

    from .._config import Specimen


class IntensityControl(Processor):  # type: ignore
    """Regulates the intensity of an incoming image.

    Emulates the behavior of a light source intensity control.
    The image incoming from a microscope is multiplied by
    a percentage factor (between 0 and 1) to simulate the
    intensity control.
    """

    def __init__(self, source: Union[Detector, npt.NDArray[Any]]):
        super().__init__(source, multi_threaded=False)
        self._intensity = 0.0

    def _fetch(self, source: npt.NDArray[Any]) -> npt.NDArray[Any]:
        return source * self.intensity

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

    @property
    def position(self) -> u.Quantity[u.um]:
        """The current position of the stage along the axis."""
        return self._position

    @position.setter
    def position(self, value: u.Quantity[u.um]) -> None:
        self._position = self.step_size * np.round(value.to(u.um) / self.step_size)


class WidefieldMicroscope:
    """A container of multiple OpenWFS components.

    Each component is chained together to provide a comprehensive control
    over a widefield microscope system. The components are:

    - A microscope.
    - A shutter.
    - An intensity control.
    - A camera.

    The components are chained as follows:

    microscope -> shutter -> intensity control -> camera

    Parameters
    ----------
    source: Union[Detector, npt.NDArray[Any]]
        The source of the microscope.
    sensor_shape: tuple[int, int]
        The shape of the fake camera sensor (width, height).
    numerical_aperture: ``float``, keyword-only
        The numerical aperture of the microscope.
    wavelength: ``float``, keyword-only
        The wavelength of the light source (in nanometers).
    magnification: ``float``, keyword-only
        The magnification factor of the microscope.

    """

    def __init__(
        self,
        source: Union[Detector, npt.NDArray[Any]],
        sensor_shape: tuple[int, int],
        *,
        numerical_aperture: float,
        wavelength: float,
        magnification: float,
    ):
        xy_stage = XYStage(u.Quantity(1, "um"), u.Quantity(1, "um"))
        z_stage = Stage("z", u.Quantity(1, "um"))
        wavelength = u.Quantity(wavelength, "nm")
        self._microscope = Microscope(
            source=source,
            numerical_aperture=numerical_aperture,
            wavelength=wavelength,
            magnification=magnification,
            xy_stage=xy_stage,
            z_stage=z_stage,
        )
        self.shutter = Shutter(source=self._microscope)
        self.light = IntensityControl(source=self.shutter)
        self._camera = Camera(
            source=self.light, digital_max=255, shot_noise=True, shape=sensor_shape
        )


class MicroscopeFactory:
    """Factory class for creating and sharing a unique WidefieldMicroscope instance."""

    container: ClassVar[Optional[WidefieldMicroscope]] = None
    specimen: ClassVar[Optional[Specimen]] = None
    sensor_shape: ClassVar[Optional[tuple[int, int]]] = None

    @classmethod
    def get_setup(cls) -> WidefieldMicroscope:
        """Return a reference to the ``WidefieldMicroscope`` instance.

        If the instance does not exist, create it with the provided arguments.
        """
        if cls.container is None:
            assert cls.specimen is not None
            assert cls.sensor_shape is not None
            # TODO: generalize the source generation
            source = np.random.randint(
                -10000, 10, cls.specimen.resolution, dtype=np.int16
            )
            source = np.maximum(source, 0)
            cls.container = WidefieldMicroscope(
                source=source,
                sensor_shape=cls.sensor_shape,
                numerical_aperture=cls.specimen.numerical_aperture,
                wavelength=cls.specimen.wavelength,
                magnification=cls.specimen.magnification,
            )
        return cls.container

    @classmethod
    def setup_factory(cls, specimen: Specimen, sensor_shape: tuple[int, int]) -> None:
        if cls.specimen is None:
            cls.specimen = specimen
        if cls.sensor_shape is None:
            cls.sensor_shape = sensor_shape
