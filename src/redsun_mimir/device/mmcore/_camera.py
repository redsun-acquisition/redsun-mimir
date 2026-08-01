from __future__ import annotations

from typing import TYPE_CHECKING

from ophyd_async.core import StandardDetector
from pymmcore_plus import CMMCorePlus
from redsun.log import Loggable
from redsun.storage import BaseStorage, SessionPathProvider, register_storage
from redsun.storage.backends._acquire_zarr import AcquireZarrIO

from redsun_mimir.device._logics import BaseDataLogic, BaseTriggerLogic
from redsun_mimir.device.signals import readable_buffer_signal

from ._backend import (
    mm_exposure_signal,
    mm_property_signal,
    mm_roi_signal,
)
from ._common import MMAdapterInfo
from ._logics import MMAcquireLogic

if TYPE_CHECKING:
    from typing import Final

    from ophyd_async.core import SignalRW

LIVE_PERIOD: Final[float] = 1 / 60.0  # 60 Hz live view update rate


class MMBaseCameraDevice(StandardDetector, Loggable):
    """Base camera wrapper for Micro-Manager Core.

    Parameters
    ----------
    name : str
        Name of this device.
    pixel_dtype: SignalRW[str]
        Signal for the pixel data type.
    adapter_info: str
        Information about the Micro-Manager adapter and device to use.
    storage : BaseStorage | None
        Storage backend this camera writes frames to. Devices receive
        storage rather than reaching for a module-global singleton: pass an
        already-constructed [`BaseStorage`][redsun.storage.BaseStorage] to
        share one store across detectors (register it with `eager_open`
        disabled on every data logic in the group). If omitted, a
        camera-private store is built from
        [`AcquireZarrIO`][redsun.storage.backends._acquire_zarr.AcquireZarrIO]
        and a default [`SessionPathProvider`][redsun.storage.SessionPathProvider].
        Either way the instance is published in the process-wide registry
        under `name` (see
        [`register_storage`][redsun.storage.register_storage]) so sibling
        components - e.g. a median presenter deriving a key from this
        camera's stream - can retrieve the same storage via
        [`get_storage`][redsun.storage.get_storage].
    """

    def __init__(
        self,
        name: str,
        *,
        core: CMMCorePlus,
        pixel_dtype: SignalRW[str],
        adapter_info: MMAdapterInfo,
        storage: BaseStorage | None = None,
        live_period: float = LIVE_PERIOD,
    ) -> None:
        self.core = core
        if self.core.getCameraDevice() != "":
            raise RuntimeError("Only one camera device can be active at a time. ")
        self.core.loadDevice(name, adapter_info.adapter, adapter_info.device)
        self.core.initializeDevice(name)
        self.core.setCameraDevice(name)
        self.storage = storage or BaseStorage(
            io=AcquireZarrIO(), path_provider=SessionPathProvider()
        )
        register_storage(name, self.storage)
        self.core.clearROI()

        # for simplicity, hardcode
        # the default exposure time to 100 ms
        self.core.setExposure(100.0)
        self.exposure = mm_exposure_signal(self.core, name)
        self.roi = mm_roi_signal(self.core, name)
        self.pixel_dtype = pixel_dtype

        self.buffer, setter = readable_buffer_signal(self.roi, self.pixel_dtype)

        acquire_logic = MMAcquireLogic(
            core=self.core, set_buffer=setter, live_period=live_period
        )

        trigger_logic = BaseTriggerLogic(
            datakey_name=name,
            storage=self.storage,
            acquire=acquire_logic,
            roi=self.roi,
            dtype=pixel_dtype,
        )

        data_logic = BaseDataLogic(
            storage=self.storage,
            acquire=acquire_logic,
            roi=self.roi,
            dtype=pixel_dtype,
        )

        self.add_detector_logics(trigger_logic, acquire_logic, data_logic)
        self.add_config_signals(self.exposure, self.roi, pixel_dtype)
        super().__init__(name=name)


class MMDemoCamera(MMBaseCameraDevice):
    """Demo camera device."""

    def __init__(
        self,
        name: str,
        *,
        storage: BaseStorage | None = None,
        live_period: float = 0.1,
    ) -> None:
        # numpy to adapter dtype mapping
        pixel_dtype: dict[str, str] = {
            "uint8": "8bit",
        }
        self.core = CMMCorePlus.instance()
        self.pixel_dtype = mm_property_signal(
            self.core, name, "PixelType", enum_map=pixel_dtype
        )
        adapter_info = MMAdapterInfo(adapter="DemoCamera", device="DCam")
        super().__init__(
            name,
            core=self.core,
            pixel_dtype=self.pixel_dtype,
            adapter_info=adapter_info,
            storage=storage,
            live_period=live_period,
        )
        self.core.setProperty(name, "PixelType", "8bit")


class MMDahengCamera(MMBaseCameraDevice):
    """Daheng camera device."""

    def __init__(
        self,
        name: str,
        *,
        storage: BaseStorage | None = None,
        live_period: float = 0.1,
    ) -> None:
        # numpy to adapter dtype mapping
        pixel_dtype: dict[str, str] = {
            "uint16": "Mono10",
        }
        self.core = CMMCorePlus.instance()
        self.pixel_dtype = mm_property_signal(
            self.core, name, "PixelType", enum_map=pixel_dtype
        )
        adapter_info = MMAdapterInfo(adapter="DahengGalaxy", device="DahengCamera")
        super().__init__(
            name,
            core=self.core,
            pixel_dtype=self.pixel_dtype,
            adapter_info=adapter_info,
            storage=storage,
            live_period=live_period,
        )
        self.core.setProperty(name, "PixelType", "Mono10")
