from __future__ import annotations

import time
from typing import TYPE_CHECKING, TypeVar, cast

import numpy as np
from ophyd_async.core import SignalBackend, SignalRW, make_datakey
from ophyd_async.core._signal_backend import make_metadata

from redsun_mimir.device._common import DEFAULT_TIMEOUT
from redsun_mimir.protocols import Array2D, ROIType

if TYPE_CHECKING:
    from bluesky.protocols import Reading
    from event_model import DataKey
    from ophyd_async.core import Callback
    from pymmcore_plus import CMMCorePlus as Core

    from redsun_mimir.device._common import AxisType

PropT = TypeVar("PropT", bound=int | float | str)


class MMPropertySignalBackend(SignalBackend[PropT]):
    """MM device property signal backend.

    Parameters
    ----------
    label: str
        The MM device label (e.g. ``"Camera"``).
    property: str
        The MM property name (e.g. ``"Exposure"``).
    core: pymmcore_plus.CMMCorePlus
        The Micro-Manager core instance.
    readonly: bool, optional
        If True, the signal will be read-only and attempts to write will raise an error.
    enum_map: dict[str, str] | None, optional
        Optional mapping from MM enum values to human-readable strings, when the property is an enum.
    """

    def __init__(
        self,
        label: str,
        property: str,
        core: Core,
        readonly: bool = False,
        enum_map: dict[str, str] | None = None,
        datatype: type[PropT] | None = None,
    ):
        self.enum_map = enum_map
        self.current_enum: str | None = None
        if self.enum_map is not None:
            self._inverse_map = {v: k for k, v in self.enum_map.items()}
        self.readonly = readonly
        self.prop_obj = core.getPropertyObject(label, property)
        self._callback: Callback[Reading[PropT]] | None = None
        super().__init__(datatype)

    def source(self, name: str, read: bool) -> str:
        """Return the source URI for this signal."""
        src = f"mmcore://{self.prop_obj.device}-{self.prop_obj.name}"
        if self.readonly:
            src += "_readonly"
        return src

    async def connect(self, timeout: float) -> None: ...

    async def put(self, value: PropT | None) -> None:
        """Write *value* to the MM property."""
        if self.readonly:
            raise RuntimeError("This signal is read-only and cannot be written to.")
        if self.enum_map is not None:
            value = self.enum_map[value]  # type: ignore
        self.prop_obj.setValue(value)

    async def get_value(self) -> PropT:
        return await self.get()

    async def get(self) -> PropT:
        return cast("PropT", self.prop_obj.value)

    async def get_setpoint(self) -> PropT:
        return await self.get_value()

    async def get_reading(self) -> Reading[PropT]:
        value = await self.get_value()
        return {"value": value, "timestamp": time.time(), "alarm_severity": 0}

    async def get_datakey(self, source: str) -> DataKey:
        assert self.datatype is not None, (
            "SignalBackend must have a known datatype to produce a DataKey"
        )

        def read_property() -> tuple[
            PropT, bool, float | None, float | None, list[str]
        ]:
            value = cast("PropT", self.prop_obj.value)
            has_limits = self.prop_obj.hasLimits()
            lo = self.prop_obj.lowerLimit() if has_limits else None
            hi = self.prop_obj.upperLimit() if has_limits else None
            allowed = list(self.prop_obj.allowedValues())
            return value, has_limits, lo, hi, allowed

        raw, has_limits, lo, hi, allowed = read_property()

        value = self.datatype(raw)
        metadata = make_metadata(self.datatype)

        if has_limits and lo is not None and hi is not None:
            metadata["limits"] = {
                "control": {"low": lo, "high": hi},
            }

        if allowed:
            metadata["choices"] = allowed

        return make_datakey(self.datatype, value, source, metadata)  # type: ignore

    def set_callback(self, callback: Callback[Reading[PropT]] | None) -> None:
        """Observe changes to the current value, timestamp and severity."""
        self._callback = callback

        def on_change(_: str) -> None:
            value = cast("PropT", self.prop_obj.value)
            if self.enum_map is not None and value in self.enum_map.values():
                # get the key corresponding to the current enum value, if it exists
                value = self._inverse_map[value]  # type: ignore
            reading: Reading[PropT] = {"value": value, "timestamp": time.time()}
            if self._callback is not None:
                self._callback(reading)

        sig = self.prop_obj.valueChanged
        sig.disconnect()

        if self._callback is not None:
            sig.connect(on_change)


class MMExposureSignalBackend(SignalBackend[float]):
    """Exposure signal backend for MM camera devices.

    Parameters
    ----------
    label: str
        The MM device label of the camera (e.g. ``"Camera"``).
    core: pymmcore_plus.CMMCorePlus
        The Micro-Manager core instance.
    initial_exposure: float, optional
        If provided, sets the initial exposure time in milliseconds.
    """

    def __init__(self, label: str, core: Core, initial_exposure: float | None = None):
        self.label = label
        self.core = core
        if initial_exposure is not None:
            self.core.setExposure(initial_exposure)
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
        dtype_numpy = np.dtype(int).str

        descriptor: DataKey = {
            "dtype": "array",
            "shape": (4,),
            "source": source,
            "dtype_numpy": dtype_numpy,
            **make_metadata(self.datatype, units="px"),
        }
        return descriptor

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


class MMBufferSignalBackend(SignalBackend[Array2D]):
    """Signal backend for the camera image buffer."""

    def __init__(self, label: str, core: Core, buffer_size: tuple[int, int]):
        self.label = label
        self.core = core
        self.buffer_size = buffer_size
        self._callback: Callback[Reading[Array2D]] | None = None
        self._buffer: Array2D = np.zeros(buffer_size, dtype=np.uint16)
        super().__init__(np.ndarray)

    def source(self, name: str, read: bool) -> str:
        """Return the source URI for this signal."""
        return f"mmcore://{self.label}-buffer"

    async def update_size(self, new_size: tuple[int, int]) -> None:
        """Update the buffer size and reallocate the buffer array."""
        self.buffer_size = new_size
        self._buffer = np.zeros(new_size, dtype=np.uint16)

    async def connect(self, timeout: float) -> None: ...

    async def put(self, value: Array2D | None) -> None:
        """Write *value* to the MM property."""
        if value is not None:
            self._buffer = value.copy()

    async def get_value(self) -> Array2D:
        """Return the current property value cast to the declared datatype."""
        return await self.get()

    async def get(self) -> Array2D:
        return self._buffer

    async def get_setpoint(self) -> Array2D:
        return await self.get()

    async def get_reading(self) -> Reading[Array2D]:
        """Return a Bluesky Reading with the current value and timestamp."""
        value = await self.get()
        return {"value": value, "timestamp": time.time()}

    async def get_datakey(self, source: str) -> DataKey:
        assert self.datatype is not None, (
            "SignalBackend must have a known datatype to produce a DataKey"
        )
        width, height = self._buffer.shape
        value = (width, height)
        metadata = make_metadata(self.datatype, units="px")
        return make_datakey(self.datatype, value, source, metadata)  # type: ignore

    def set_callback(self, callback: Callback[Reading[Array2D]] | None) -> None:
        """Observe changes to the current value, timestamp and severity."""
        self._callback = callback


class MMCorePositionSignalBackend(SignalBackend[float]):
    """Signal backend for a generic MM device property representing an axis position."""

    def __init__(self, label: str, core: Core, axis: AxisType, units: str = "um"):
        self.label = label
        self.core = core
        self.axis = axis
        self.units = units
        self._callback: Callback[Reading[float | int]] | None = None
        super().__init__(float)

    def source(self, name: str, read: bool) -> str:
        """Return the source URI for this signal."""
        return f"mmcore://{self.label}_{self.axis}"

    async def connect(self, timeout: float) -> None: ...

    async def put(self, value: float | None) -> None:
        if value is not None:
            if self.axis in ["x", "y"]:
                current_pos = self.core.getXYPosition(self.label)
                if self.axis == "x":
                    new_pos = (value, current_pos[1])
                else:
                    new_pos = (current_pos[0], value)
                self.core.setXYPosition(self.label, new_pos[0], new_pos[1])
            else:  # axis == "z"
                self.core.setPosition(self.label, value)

    async def get_value(self) -> float:
        """Return the current property value cast to the declared datatype."""
        return await self.get()

    async def get(self) -> float:
        if self.axis in ["x", "y"]:
            position = self.core.getXYPosition(self.label)
            return position[0] if self.axis == "x" else position[1]
        else:  # axis == "z"
            return self.core.getPosition(self.label)

    async def get_setpoint(self) -> float:
        return await self.get()

    async def get_reading(self) -> Reading[float]:
        """Return a Bluesky Reading with the current value and timestamp."""
        value = await self.get()
        return {"value": value, "timestamp": time.time()}

    async def get_datakey(self, source: str) -> DataKey:
        assert self.datatype is not None, (
            "SignalBackend must have a known datatype to produce a DataKey"
        )
        value = await self.get()
        metadata = make_metadata(self.datatype, units=self.units)
        # TODO: how to include the limits of the axis stage?
        # there seems to be no API...
        return make_datakey(self.datatype, value, source, metadata)

    def set_callback(self, callback: Callback[Reading[float]] | None) -> None:
        """Observe changes to the current value, timestamp and severity."""
        self._callback = callback

        def on_change(_: str, pos: float) -> None:
            reading: Reading[float] = {"value": pos, "timestamp": time.time()}
            if self._callback is not None:
                self._callback(reading)

        sig = self.core.events.stagePositionChanged
        sig.disconnect()
        if self._callback is not None:
            sig.connect(on_change)


def mm_property_signal(
    core: Core,
    device_label: str,
    property_name: str,
    *,
    readonly: bool = False,
    enum_map: dict[str, str] | None = None,
    datatype: type[PropT] | None = None,
) -> SignalRW[PropT]:
    """Create a read-write Signal backed by a Micro-Manager device property.

    Parameters
    ----------
    core: pymmcore_plus.CMMCorePlus
        The Micro-Manager core.
    device_label: str
        The MM device label (e.g. ``"Camera"``).
    property_name: str
        The MM property name (e.g. ``"Exposure"``).
    enum_map: dict[str, str] | None, optional
        Optional mapping from MM enum values to human-readable strings,
        when the property is an enum.
    readonly: bool, optional
        If True, the signal will be read-only and attempts to write will raise an error.
    datatype: type[PropT] | None, optional
        Optional explicit datatype for the signal.
    """
    backend = MMPropertySignalBackend(
        device_label,
        property_name,
        core,
        readonly=readonly,
        enum_map=enum_map,
        datatype=datatype,
    )
    return SignalRW(backend, name=property_name, timeout=DEFAULT_TIMEOUT)


def mm_position_signal(
    core: Core, device_label: str, axis: AxisType, units: str = "um"
) -> SignalRW[float]:
    """Create a read-write Signal for a MM device position property.

    Parameters
    ----------
    core: pymmcore_plus.CMMCorePlus
        The Micro-Manager core.
    device_label: str
        The MM device label (e.g. ``"XYStage"``).
    axis: AxisType
        The axis to control ("x", "y", or "z").
    units: str, optional
        The physical units of the position (e.g. "um" or "mm"). This is used in the signal metadata.
    """
    backend = MMCorePositionSignalBackend(device_label, core, axis, units)
    return SignalRW(backend, name="position", timeout=DEFAULT_TIMEOUT)


def mm_exposure_signal(
    core: Core,
    device_label: str,
    initial_exposure: float | None = None,
) -> SignalRW[float]:
    """Create a read-write Signal for the camera exposure time.

    Parameters
    ----------
    core: pymmcore_plus.CMMCorePlus
        The Micro-Manager core.
    device_label: str
        The MM device label of the camera (e.g. ``"Camera"``).
    initial_exposure: float | None
        Optional initial exposure time in milliseconds to set when the signal is created.
    """
    backend = MMExposureSignalBackend(device_label, core, initial_exposure)
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


def mm_buffer_signal(
    core: Core,
    device_label: str,
    buffer_size: tuple[int, int],
) -> SignalRW[Array2D]:
    """Create a read-write Signal for the camera image buffer.

    Parameters
    ----------
    core: pymmcore_plus.CMMCorePlus
        The Micro-Manager core.
    device_label:
        The MM device label of the camera (e.g. ``"Camera"``).
    buffer_size:
        The initial size of the image buffer as a tuple (width, height).
    """
    backend = MMBufferSignalBackend(device_label, core, buffer_size)
    return SignalRW(backend, name="buffer", timeout=DEFAULT_TIMEOUT)
