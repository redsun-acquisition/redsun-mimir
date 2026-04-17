from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, cast

import numpy as np
from ophyd_async.core import SignalBackend, SignalRW, make_datakey
from ophyd_async.core._signal_backend import Primitive, PrimitiveT, make_metadata

if TYPE_CHECKING:
    from bluesky.protocols import Reading
    from event_model import DataKey
    from ophyd_async.core import Callback
    from pymmcore_plus import CMMCorePlus as Core

DEFAULT_TIMEOUT = 1.0


class MMPropertySignalBackend(SignalBackend[PrimitiveT]):
    def __init__(self, label: str, property: str, core: Core):
        self.prop_obj = core.getPropertyObject(label, property)
        datatype = cast("type[PrimitiveT]", self.prop_obj.type().to_python())
        self._callback: Callback[Reading[PrimitiveT]] | None = None
        super().__init__(datatype)

    def source(self, name: str, read: bool) -> str:
        """Return the source URI for this signal."""
        return f"mmcore://{self.prop_obj.device}-{self.prop_obj.name}"

    async def connect(self, timeout: float) -> None: ...

    async def put(self, value: PrimitiveT | None) -> None:
        """Write *value* to the MM property."""
        self.prop_obj.setValue(value)

    async def get_value(self) -> PrimitiveT:
        """Return the current property value cast to the declared datatype."""
        return await self.get()

    async def get(self) -> PrimitiveT:
        return cast("PrimitiveT", self.prop_obj.value)

    async def get_setpoint(self) -> PrimitiveT:
        return await self.get_value()

    async def get_reading(self) -> Reading[PrimitiveT]:
        """Return a Bluesky Reading with the current value and timestamp."""
        value = await self.get_value()
        return {"value": value, "timestamp": time.time()}

    async def get_datakey(self, source: str) -> DataKey:
        assert self.datatype is not None, (
            "SignalBackend must have a known datatype to produce a DataKey"
        )

        def read_property() -> tuple[
            Primitive, bool, float | None, float | None, list[str]
        ]:
            value = cast("Primitive", self.prop_obj.value)
            has_limits = self.prop_obj.hasLimits()
            lo = self.prop_obj.lowerLimit() if has_limits else None
            hi = self.prop_obj.upperLimit() if has_limits else None
            allowed = list(self.prop_obj.allowedValues())
            return value, has_limits, lo, hi, allowed

        raw, has_limits, lo, hi, allowed = read_property()

        value = cast("PrimitiveT", self.datatype(raw))
        metadata = make_metadata(self.datatype)

        if has_limits and lo is not None and hi is not None:
            metadata["limits"] = {
                "control": {"low": lo, "high": hi},
            }

        if allowed:
            metadata["choices"] = allowed

        return make_datakey(self.datatype, value, source, metadata)

    def set_callback(self, callback: Callback[Reading[PrimitiveT]] | None) -> None:
        """Observe changes to the current value, timestamp and severity."""
        self._callback = callback

        def on_change(_: str) -> None:
            value = cast("Primitive", self.prop_obj.value)
            reading: Reading[Primitive] = {"value": value, "timestamp": time.time()}
            if self._callback is not None:
                self._callback(reading)  # type: ignore

        sig = self.prop_obj.valueChanged
        sig.disconnect()

        if self._callback is not None:
            sig.connect(on_change)


class MMExposureSignalBackend(SignalBackend[float]):
    def __init__(self, label: str, core: Core):
        self.label = label
        self.core = core
        self._callback: Callback[Reading[float]] | None = None
        super().__init__(float)

    def source(self, name: str, read: bool) -> str:
        """Return the source URI for this signal."""
        return f"mmcore://{self.label}-exposure"

    async def connect(self, timeout: float) -> None: ...

    async def put(self, value: float | None) -> None:
        """Write *value* to the MM property."""
        if value is not None:
            self.core.setExposure(value)

    async def get_value(self) -> float:
        """Return the current property value cast to the declared datatype."""
        return await self.get()

    async def get(self) -> float:
        return self.core.getExposure()

    async def get_setpoint(self) -> float:
        return await self.get_value()

    async def get_reading(self) -> Reading[float]:
        """Return a Bluesky Reading with the current value and timestamp."""
        value = await self.get_value()
        return {"value": value, "timestamp": time.time()}

    async def get_datakey(self, source: str) -> DataKey:
        assert self.datatype is not None, (
            "SignalBackend must have a known datatype to produce a DataKey"
        )
        value = self.core.getExposure()
        metadata = make_metadata(self.datatype, units="ms")
        return make_datakey(self.datatype, value, source, metadata)

    def set_callback(self, callback: Callback[Reading[float]] | None) -> None:
        """Observe changes to the current value, timestamp and severity."""
        self._callback = callback

        def on_change(_: str, exposure: float) -> None:
            reading: Reading[float] = {"value": exposure, "timestamp": time.time()}
            if self._callback is not None:
                self._callback(reading)

        sig = self.core.events.exposureChanged
        sig.disconnect()
        if self._callback is not None:
            sig.connect(on_change)


ROIType = np.ndarray[tuple[int, int, int, int], Any]  # x, y, width, height


class MMROISignalBackend(SignalBackend[ROIType]):
    def __init__(self, label: str, core: Core):
        self.label = label
        self.core = core
        self._callback: Callback[Reading[ROIType]] | None = None
        super().__init__(ROIType)

    def source(self, name: str, read: bool) -> str:
        """Return the source URI for this signal."""
        return f"mmcore://{self.label}-roi"

    async def connect(self, timeout: float) -> None: ...

    async def put(self, value: ROIType | None) -> None:
        """Write *value* to the MM property."""
        if value is not None:
            x, y, width, height = tuple(value.tolist())
            self.core.setROI(x, y, width, height)

    async def get_value(self) -> ROIType:
        """Return the current property value cast to the declared datatype."""
        return await self.get()

    async def get(self) -> ROIType:
        x, y, width, height = self.core.getROI()
        array = np.array([x, y, width, height], dtype=int)
        return array

    async def get_setpoint(self) -> ROIType:
        return await self.get()

    async def get_reading(self) -> Reading[ROIType]:
        """Return a Bluesky Reading with the current value and timestamp."""
        value = await self.get()
        return {"value": value, "timestamp": time.time()}

    async def get_datakey(self, source: str) -> DataKey:
        assert self.datatype is not None, (
            "SignalBackend must have a known datatype to produce a DataKey"
        )

        x, y, width, height = self.core.getROI()
        value = (x, y, width, height)
        metadata = make_metadata(self.datatype, units="px")
        return make_datakey(self.datatype, value, source, metadata)  # type: ignore

    def set_callback(self, callback: Callback[Reading[ROIType]] | None) -> None:
        """Observe changes to the current value, timestamp and severity."""
        self._callback = callback

        def on_change(_: str, x: int, y: int, width: int, height: int) -> None:
            value = np.array([x, y, width, height], dtype=int)
            reading: Reading[ROIType] = {"value": value, "timestamp": time.time()}
            if self._callback is not None:
                self._callback(reading)

        sig = self.core.events.roiSet
        sig.disconnect()
        if self._callback is not None:
            sig.connect(on_change)


def mm_property_signal(
    core: Core,
    device_label: str,
    property_name: str,
) -> SignalRW[PrimitiveT]:
    """Create a read-write Signal backed by a Micro-Manager device property.

    Parameters
    ----------
    core: pymmcore_plus.CMMCorePlus
        The Micro-Manager core.
    device_label:
        The MM device label (e.g. ``"Camera"``).
    property_name:
        The MM property name (e.g. ``"Exposure"``).
    """
    backend = MMPropertySignalBackend[PrimitiveT](device_label, property_name, core)
    return SignalRW(backend, name=property_name, timeout=DEFAULT_TIMEOUT)


def mm_exposure_signal(
    core: Core,
    device_label: str,
) -> SignalRW[float]:
    """Create a read-write Signal for the camera exposure time.

    Parameters
    ----------
    core: pymmcore_plus.CMMCorePlus
        The Micro-Manager core.
    device_label:
        The MM device label of the camera (e.g. ``"Camera"``).
    """
    backend = MMExposureSignalBackend(device_label, core)
    return SignalRW(backend, name="exposure", timeout=DEFAULT_TIMEOUT)


def mm_roi_signal(
    core: Core,
    device_label: str,
) -> SignalRW[ROIType]:
    """Create a read-write Signal for the camera ROI.

    Parameters
    ----------
    core: pymmcore_plus.CMMCorePlus
        The Micro-Manager core.
    device_label:
        The MM device label of the camera (e.g. ``"Camera"``).
    """
    backend = MMROISignalBackend(device_label, core)
    return SignalRW(backend, name="roi", timeout=DEFAULT_TIMEOUT)
