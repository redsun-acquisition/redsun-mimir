from __future__ import annotations

from ophyd_async.core import (
    StandardDetector,
    StandardReadable,
    StandardReadableFormat,
)
from pymmcore_plus import CMMCorePlus
from redsun.log import Loggable
from redsun.storage import create_writer

from ._backend import mm_exposure_signal, mm_roi_signal


class MMBaseCameraDevice(StandardDetector, StandardReadable, Loggable):
    """Base camera wrapper for Micro-Manager Core.

    Parameters
    ----------
    name : str
        Name of this device.
    writer : str
        Writer type identifier.
        See [`WriterType`][redsun.storage.WriterType] for supported values.
    """

    def __init__(self, name: str, *, writer: str) -> None:
        super().__init__(name=name)
        self.core = CMMCorePlus.instance()
        self.writer = create_writer(writer)

        with self.add_children_as_readables(StandardReadableFormat.CONFIG_SIGNAL):
            self.exposure = mm_exposure_signal(self.core, device_label=name)
            self.roi = mm_roi_signal(self.core, device_label=name)
