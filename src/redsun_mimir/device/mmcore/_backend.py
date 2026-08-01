"""Micro-Manager signals, built on callable-backed soft signals.

Every signal wraps a `pymmcore-plus` call through the ``getter``/``setter``
hooks of ophyd-async's `SoftSignalBackend`. The backend's cache stays the
single source of truth: ``getter`` refreshes it on every read, ``setter``
pushes to the hardware and - by returning ``None`` - has the cache refreshed
from the device immediately afterwards.

``poll_period`` only takes effect while something is subscribed to a signal;
Micro-Manager's own change events are not hooked up.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING, Final, cast

import numpy as np
from ophyd_async.core import (
    MovableLogic,
    StandardMovable,
    StandardReadable,
    StrictEnum,
    set_and_wait_for_other_value,
    soft_signal_r_and_setter,
    soft_signal_rw,
)

if TYPE_CHECKING:
    from ophyd_async.core import SignalRW, TimeoutCalculator
    from pymmcore_plus import CMMCorePlus as Core

    from redsun_mimir.device._logics import AxisType
    from redsun_mimir.protocols import ROIType

#: How often a *subscribed* signal re-reads the device. Micro-Manager pushes
#: change events of its own, but a soft signal has no place to hook them, so
#: subscribers are served by polling instead.
POLL_PERIOD: Final[float] = 0.2


def mm_property_signal(
    core: Core,
    device_label: str,
    property_name: str,
    *,
    enum_map: dict[str, str],
) -> SignalRW[str]:
    """Create a signal for a Micro-Manager property with a fixed set of choices.

    The signal speaks the *caller's* vocabulary, not Micro-Manager's:
    *enum_map* maps the value seen by the application (e.g. ``"uint8"``) to
    the adapter's own spelling (e.g. ``"8bit"``), and the translation happens
    inside the getter and setter.

    The datatype is a `StrictEnum` built from *enum_map*, which is what makes
    ophyd-async publish ``choices`` in the DataKey - the UI builds its
    combo box from those. Members are ``str`` subclasses, so a value is still
    usable anywhere a plain string is expected (``np.dtype(value)`` included).

    Parameters
    ----------
    core : CMMCorePlus
        The Micro-Manager core.
    device_label : str
        The MM device label (e.g. ``"Camera"``).
    property_name : str
        The MM property name (e.g. ``"PixelType"``).
    enum_map : dict[str, str]
        Mapping of application value to Micro-Manager value.
    """
    prop = core.getPropertyObject(device_label, property_name)
    to_mm = dict(enum_map)
    from_mm = {mm: app for app, mm in enum_map.items()}
    choices = cast(
        "type[StrictEnum]",
        # functional Enum API; mypy cannot follow it, the cast is the contract
        StrictEnum(  # type: ignore[call-arg]
            f"{device_label}_{property_name}", {v.upper(): v for v in to_mm}
        ),
    )

    def getter() -> str:
        raw = str(prop.value)
        return cast("str", choices(from_mm.get(raw, raw)))

    def setter(value: str | None) -> None:
        if value is not None:
            prop.setValue(to_mm[str(value)])

    # the initial value is deliberately static: signals are built before the
    # device is loaded into the core, so nothing here may touch it. The
    # getter refreshes the cache on the first read.
    return cast(
        "SignalRW[str]",
        soft_signal_rw(
            choices,
            cast("str", choices(next(iter(to_mm)))),
            name=property_name,
            getter=getter,
            setter=setter,
            poll_period=POLL_PERIOD,
        ),
    )


#: A Micro-Manager stage settles on its own grid rather than exactly where it
#: was sent: the demo XY stage lands within 0.006 um of any request, and
#: exposes no step-size property to derive this from. `MovableLogic.move`
#: waits for equality by default, which would never be satisfied.
POSITION_TOLERANCE: Final[float] = 0.01


@dataclass
class MMAxisLogic(MovableLogic[float]):
    """Move logic for one axis of a Micro-Manager stage."""

    tolerance: float = POSITION_TOLERANCE

    async def move(self, new_position: float, timeout: TimeoutCalculator) -> None:
        """Write the setpoint and wait for the readback to land within tolerance."""
        await set_and_wait_for_other_value(
            self.setpoint,
            new_position,
            self.readback,
            lambda value: bool(np.isclose(value, new_position, atol=self.tolerance)),
            timeout=timeout(),
        )


class MMAxis(StandardReadable, StandardMovable[float]):
    """One axis of a Micro-Manager stage.

    Parameters
    ----------
    core : CMMCorePlus
        The Micro-Manager core.
    device_label : str
        The MM device label (e.g. ``"XYStage"``).
    axis : AxisType
        The axis to control (``"x"``, ``"y"`` or ``"z"``).
    units : str, optional
        Physical units of the position, published in the DataKey.
    name : str, optional
        Device name. Assigned by the parent when held in a ``DeviceMap``.
    """

    def __init__(
        self,
        core: Core,
        device_label: str,
        axis: AxisType,
        units: str = "um",
        name: str = "",
    ) -> None:
        lateral = axis in ("x", "y")

        def getter() -> float:
            if not lateral:
                return core.getPosition(device_label)
            x, y = core.getXYPosition(device_label)
            return x if axis == "x" else y

        async def setter(value: float | None) -> None:
            if value is None:
                return
            if not lateral:
                core.setPosition(device_label, value)
            else:
                x, y = core.getXYPosition(device_label)
                core.setXYPosition(
                    device_label,
                    value if axis == "x" else x,
                    value if axis == "y" else y,
                )
            # a stage takes time to travel: block the *set* until it has
            # arrived, so a plan's move completes when the axis is really
            # there. waitForDevice is a blocking core call, hence the thread.
            await asyncio.to_thread(core.waitForDevice, device_label)

        with self.add_children_as_readables():
            self.readback, _ = soft_signal_r_and_setter(
                float,
                0.0,
                units=units,
                getter=getter,
                poll_period=POLL_PERIOD,
            )
        self.setpoint = soft_signal_rw(float, 0.0, units=units, setter=setter)

        super().__init__(name)

    @cached_property
    def movable_logic(self) -> MovableLogic[float]:
        """Setpoint and readback of this axis."""
        return MMAxisLogic(setpoint=self.setpoint, readback=self.readback)


def mm_exposure_signal(
    core: Core,
    device_label: str,
    initial_exposure: float | None = None,
) -> SignalRW[float]:
    """Create a signal for the camera exposure time, in milliseconds.

    Parameters
    ----------
    core : CMMCorePlus
        The Micro-Manager core.
    device_label : str
        The MM device label of the camera (e.g. ``"Camera"``).
    initial_exposure : float | None, optional
        Exposure to apply when the signal is created.
    """
    if initial_exposure is not None:
        core.setExposure(device_label, initial_exposure)

    def getter() -> float:
        return core.getExposure(device_label)

    def setter(value: float | None) -> None:
        if value is not None:
            core.setExposure(device_label, value)

    return soft_signal_rw(
        float,
        0.0,
        name="exposure",
        units="ms",
        getter=getter,
        setter=setter,
        poll_period=POLL_PERIOD,
    )


def mm_roi_signal(core: Core, device_label: str) -> SignalRW[ROIType]:
    """Create a signal for the camera ROI as ``[x, y, width, height]``.

    Parameters
    ----------
    core : CMMCorePlus
        The Micro-Manager core.
    device_label : str
        The MM device label of the camera (e.g. ``"Camera"``).
    """

    def getter() -> np.ndarray:
        return np.array(core.getROI(device_label), dtype=int)

    def setter(value: np.ndarray | None) -> None:
        if value is None:
            return
        x, y, width, height = (int(v) for v in np.asarray(value).tolist())
        core.setROI(device_label, x, y, width, height)

    return cast(
        "SignalRW[ROIType]",
        soft_signal_rw(
            np.ndarray,
            np.zeros(4, dtype=int),
            name="roi",
            units="px",
            getter=getter,
            setter=setter,
            poll_period=POLL_PERIOD,
        ),
    )
