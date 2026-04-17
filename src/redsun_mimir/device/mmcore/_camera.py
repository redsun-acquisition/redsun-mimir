"""MMCore camera device — ophyd-async ``StandardDetector`` wrapper."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, ClassVar

import numpy as np
from ophyd_async.core import (
    AsyncStatus,
    SignalR,
    StandardDetector,
    soft_signal_r_and_setter,
)
from pymmcore_plus import CMMCorePlus as Core
from redsun.log import Loggable
from redsun.storage import WriterType, create_writer
from redsun.storage.protocols import HasWriterLogic
from redsun.utils.descriptors import make_descriptor, make_key, make_reading, parse_key

from redsun_mimir.device.mmcore.configs import (
    BaseCamConfig,
    DahengCamConfig,
    DemoCamConfig,
)

if TYPE_CHECKING:
    from typing import Any, Literal

    from bluesky.protocols import Descriptor, Reading
    from ophyd_async.core import DeviceMock, PathProvider
    from redsun.storage import DataWriter


class MMCoreCameraDevice(StandardDetector, HasWriterLogic, Loggable):
    """Camera wrapper for Micro-Manager Core.

    Parameters
    ----------
    name : str
        Name of the device instance; used to register with the core.
    writer : str
        Name of the writer backend to use; passed to
        [`create_writer`][redsun.storage.create_writer] to construct the
        writer instance that is injected into the arm and trigger logic.
    config : Literal["demo", "daheng"], optional
        Configuration preset to use; determines the camera model and
        properties.

        Defaults to "demo".
    """

    initialized: ClassVar[bool] = False

    buffer: SignalR[np.ndarray]

    def __init__(
        self,
        name: str,
        /,
        writer: str,
        config: Literal["demo", "daheng"] = "demo",
        path_provider: PathProvider | None = None,
    ) -> None:
        self._writer = create_writer(WriterType(writer))

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

        buf, set_buf = soft_signal_r_and_setter(
            np.ndarray,
            initial_value=np.zeros(
                (self.roi[3], self.roi[2]), dtype=np.dtype(self._get_dtype(name))
            ),
        )
        self.buffer = buf
        self._set_buf = set_buf

        if path_provider is None:
            import pathlib

            from ophyd_async.core import StaticFilenameProvider, StaticPathProvider

            path_provider = StaticPathProvider(
                StaticFilenameProvider(name),
                pathlib.PurePath(pathlib.Path.home() / "redsun-storage"),
            )

        super().__init__(name=name)

        self.logger.debug(
            f"Initialized {self.cam_config.adapter} -> {self.cam_config.device}"
        )

    async def connect(
        self,
        mock: bool | DeviceMock[Any] = False,
        timeout: float = 10.0,
        force_reconnect: bool = False,
    ) -> None:
        """Connect device signals, including the ``NDArrayInfo`` soft signals."""
        await super().connect(
            mock=mock, timeout=timeout, force_reconnect=force_reconnect
        )

    def _get_dtype(self, device_name: str) -> str:
        """Return the numpy dtype string for the current pixel type."""
        return self.cam_config.numpy_dtype[self._pixelprop][
            self._core.getProperty(device_name, self._pixelprop)
        ]

    @property
    def dtype(self) -> str:
        """The currently active pixel data type of the camera, as a numpy dtype string."""
        return self._get_dtype(self.name)

    @property
    def writer(self) -> DataWriter:
        """Expose the injected writer for discovery via [`HasWriterLogic`][redsun.storage.protocols.HasWriterLogic]."""
        return self._writer

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
