"""MMCore stage device — ophyd-async ``StandardReadable`` wrapper."""

from __future__ import annotations

import asyncio
from typing import Literal

from ophyd_async.core import AsyncStatus, StandardReadable
from pymmcore_plus import CMMCorePlus as Core
from redsun.log import Loggable

from redsun_mimir.device.axis import MotorAxis
from redsun_mimir.device.mmcore.configs import (
    BaseStageConfig,
    DemoXYStageConfig,
    DemoZStageConfig,
)


class MMCoreXYAxis(MotorAxis):
    """One axis of an MMCore XY stage.

    Performs absolute moves via
    [`setXYPosition`][pymmcore_plus.CMMCorePlus.setXYPosition].

    Parameters
    ----------
    core :
        Shared ``CMMCorePlus`` instance.
    device_name :
        MMCore device label of the parent stage.
    axis :
        Which axis this object controls (``"x"`` or ``"y"``).
    units :
        Engineering unit (default ``"um"``).
    step_size :
        Initial step size.
    """

    def __init__(
        self,
        core: Core,
        device_name: str,
        axis: str,
        *,
        units: str = "um",
        step_size: float = 1.0,
    ) -> None:
        self._core = core
        self._device_name = device_name
        self._axis = axis
        super().__init__(units=units, step_size=step_size)

    @AsyncStatus.wrap
    async def set(self, value: float, **_: float) -> None:
        """Move this axis to *value* (absolute position).

        Parameters
        ----------
        value :
            Target position in the axis engineering unit.
        """
        await asyncio.to_thread(self._set_sync, value)

    def _set_sync(self, value: float) -> None:
        x, y = self._core.getXYPosition(self._device_name)
        nx = value if self._axis == "x" else x
        ny = value if self._axis == "y" else y
        self._core.setXYPosition(self._device_name, nx, ny)
        self._core.waitForDevice(self._device_name)
        self._set_position(nx if self._axis == "x" else ny)


class MMCoreZAxis(MotorAxis):
    """Z axis of an MMCore focus stage.

    Performs absolute moves via
    [`setPosition`][pymmcore_plus.CMMCorePlus.setPosition].

    Parameters
    ----------
    core :
        Shared ``CMMCorePlus`` instance.
    device_name :
        MMCore device label of the parent stage.
    units :
        Engineering unit (default ``"um"``).
    step_size :
        Initial step size.
    """

    def __init__(
        self,
        core: Core,
        device_name: str,
        *,
        units: str = "um",
        step_size: float = 1.0,
    ) -> None:
        self._core = core
        self._device_name = device_name
        super().__init__(units=units, step_size=step_size)

    @AsyncStatus.wrap
    async def set(self, value: float, **_: float) -> None:
        """Move the Z axis to *value* (absolute position).

        Parameters
        ----------
        value :
            Target position in the axis engineering unit.
        """
        await asyncio.to_thread(self._set_sync, value)

    def _set_sync(self, value: float) -> None:
        self._core.setPosition(self._device_name, value)
        self._core.waitForDevice(self._device_name)
        self._set_position(value)


class MMCoreStageDevice(StandardReadable, Loggable):
    """Container device for one or more MMCore stage axes.

    Loads and initialises the hardware via ``CMMCorePlus``, then exposes
    each axis as a typed child attribute (``device.x``, ``device.y``, or
    ``device.z``).  All movement logic lives in the individual axis objects
    ([`MMCoreXYAxis`][redsun_mimir.device.mmcore.MMCoreXYAxis] /
    [`MMCoreZAxis`][redsun_mimir.device.mmcore.MMCoreZAxis]).

    Parameters
    ----------
    name :
        Identity key of the device.
    config :
        Predefined configuration name (``"demoxy"`` or ``"demoz"``).
    """

    def __init__(self, name: str, /, config: Literal["demoxy", "demoz"] | None) -> None:
        self.stage_config: BaseStageConfig
        match config:
            case "demoxy":
                self.stage_config = DemoXYStageConfig()
            case "demoz":
                self.stage_config = DemoZStageConfig()
            case _:
                err_msg = (
                    f"Unknown stage config: {config!r}"
                    if config is not None
                    else "Stage config must be specified."
                )
                raise ValueError(err_msg)

        self._core = Core.instance()
        try:
            self._core.loadDevice(
                name, self.stage_config.adapter, self.stage_config.device
            )
            self._core.initializeDevice(name)
        except Exception as e:
            raise RuntimeError(f"Failed to initialize MMCore stage device: {e}") from e

        _axis_list = self.stage_config.axis
        _egu = self.stage_config.egu

        with self.add_children_as_readables():
            if _axis_list == ["z"]:
                self._core.setOrigin(name)
                self.z = MMCoreZAxis(
                    core=self._core,
                    device_name=name,
                    units=_egu,
                    step_size=float(self.stage_config.step_sizes.get("z", 1.0)),
                )
            elif _axis_list == ["x", "y"]:
                self._core.setOriginXY(name)
                self.x = MMCoreXYAxis(
                    core=self._core,
                    device_name=name,
                    axis="x",
                    units=_egu,
                    step_size=float(self.stage_config.step_sizes.get("x", 1.0)),
                )
                self.y = MMCoreXYAxis(
                    core=self._core,
                    device_name=name,
                    axis="y",
                    units=_egu,
                    step_size=float(self.stage_config.step_sizes.get("y", 1.0)),
                )
            else:
                raise ValueError(
                    "Unsupported axis configuration. Only ['x', 'y'] and ['z'] are supported."
                )

        super().__init__(name=name)
        self.logger.debug(
            f"Initialized {self.stage_config.adapter} -> {self.stage_config.device}"
        )
