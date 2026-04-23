from __future__ import annotations

from typing import TYPE_CHECKING

from ophyd_async.core import (
    StandardDetector,
)
from pymmcore_plus import CMMCorePlus
from redsun.log import Loggable
from redsun.storage import create_writer

from redsun_mimir.storage import SessionPathProvider

from ._backend import (
    buffer_signal,
    mm_exposure_signal,
    mm_property_signal,
    mm_roi_signal,
)
from ._common import MMAdapterInfo
from ._logics import MMArmLogic, MMDataLogic, MMTriggerLogic

if TYPE_CHECKING:
    from ophyd_async.core import SignalRW


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
    writer : str
        Writer type identifier.
        See [`WriterType`][redsun.storage.WriterType] for supported values.
    dtype : SignalRW[str] | None
        Optional signal for the pixel data type.
    """

    def __init__(
        self,
        name: str,
        *,
        core: CMMCorePlus,
        pixel_dtype: SignalRW[str],
        adapter_info: MMAdapterInfo,
        writer: str = "zarr",
    ) -> None:
        self.core = core
        if self.core.getCameraDevice() != "":
            raise RuntimeError("Only one camera device can be active at a time. ")
        self.core.loadDevice(name, adapter_info.adapter, adapter_info.device)
        self.core.initializeDevice(name)
        self.core.setCameraDevice(name)
        self.writer = create_writer(writer)
        self.core.clearROI()

        self.exposure = mm_exposure_signal(self.core, name)
        self.roi = mm_roi_signal(self.core, name)
        self.pixel_dtype = pixel_dtype

        self.buffer, setter = buffer_signal(self.roi, self.pixel_dtype)

        trigger_logic = MMTriggerLogic(
            datakey_name=self.name,
            core=self.core,
            writer=self.writer,
            roi=self.roi,
            dtype=pixel_dtype,
        )

        arm_logic = MMArmLogic(
            datakey_name=self.name,
            core=self.core,
            writer=self.writer,
            set_buffer=setter,
        )

        data_logic = MMDataLogic(
            writer=self.writer, path_provider=SessionPathProvider()
        )

        logics: list[MMTriggerLogic | MMArmLogic | MMDataLogic] = [
            trigger_logic,
            arm_logic,
            data_logic,
        ]

        self.add_detector_logics(*logics)
        self.add_config_signals(self.exposure, self.roi, pixel_dtype)
        super().__init__(name=name)


class MMDemoCamera(MMBaseCameraDevice):
    """Demo camera device."""

    def __init__(self, name: str, *, writer: str = "zarr") -> None:
        # numpy to adapter dtype mapping
        pixel_dtype: dict[str, str] = {
            "uint8": "8bit",
            "uint16": "16bit",
            "uint32": "32bit",
        }
        self.core = CMMCorePlus.instance()
        self.pixel_dtype = mm_property_signal(
            self.core, name, "PixelType", enum_map=pixel_dtype, datatype=str
        )
        adapter_info = MMAdapterInfo(adapter="DemoCamera", device="DCam")
        super().__init__(
            name,
            core=self.core,
            pixel_dtype=self.pixel_dtype,
            adapter_info=adapter_info,
            writer=writer,
        )
