from __future__ import annotations

from typing import TYPE_CHECKING

from pymmcore_plus import CMMCorePlus as Core
from redsun.device import Device
from redsun.engine import Status
from redsun.log import Loggable

from redsun_mimir.device.axis import MotorAxis
from redsun_mimir.device.mmcore.configs import (
    BaseStageConfig,
    DemoXYStageConfig,
    DemoZStageConfig,
)

if TYPE_CHECKING:
    from typing import Any, Literal

    from bluesky.protocols import Descriptor, Reading
    from redsun.storage import PrepareInfo


class MMCoreXYAxis(MotorAxis):
    """One axis of an MMCore XY stage.

    Performs relative moves via
    [`setXYPosition`][pymmcore_plus.CMMCorePlus.setXYPosition].

    Parameters
    ----------
    name :
        Axis name; overwritten by the parent
        [`MMCoreStageDevice`][redsun_mimir.device.mmcore.MMCoreStageDevice]
        on assignment.
    egu :
        Engineering unit (``"um"``).
    step_size :
        Initial step size.
    core :
        Shared ``CMMCorePlus`` instance.
    device_name :
        MMCore device label of the parent stage.
    axis :
        Which axis this object controls (``"x"`` or ``"y"``).
    """

    def __init__(
        self,
        name: str,
        egu: str,
        step_size: float,
        core: Core,
        device_name: str,
        axis: str,
    ) -> None:
        super().__init__(name, egu, step_size)
        self._core = core
        self._device_name = device_name
        self._axis = axis

    def set(self, value: float, **_kwargs: Any) -> Status:
        """Move this axis by *value* (relative step).

        Parameters
        ----------
        value :
            Step distance in the axis engineering unit.

        Returns
        -------
        Status
            Completes immediately after the hardware call succeeds.
        """
        s = Status()
        try:
            x, y = self._core.getXYPosition(self._device_name)
            if self._axis == "x":
                self._core.setXYPosition(self._device_name, x + value, y)
            else:
                self._core.setXYPosition(self._device_name, x, y + value)
            self.position.set(self.position.get_value() + value)
            s.set_finished()
        except Exception as e:
            s.set_exception(RuntimeError(f"Failed to set XY position: {e}"))
        return s


class MMCoreZAxis(MotorAxis):
    """Z axis of an MMCore focus stage.

    Performs relative moves via
    [`setPosition`][pymmcore_plus.CMMCorePlus.setPosition].

    Parameters
    ----------
    name :
        Axis name; overwritten by the parent
        [`MMCoreStageDevice`][redsun_mimir.device.mmcore.MMCoreStageDevice]
        on assignment.
    egu :
        Engineering unit (``"um"``).
    step_size :
        Initial step size.
    core :
        Shared ``CMMCorePlus`` instance.
    device_name :
        MMCore device label of the parent stage.
    """

    def __init__(
        self,
        name: str,
        egu: str,
        step_size: float,
        core: Core,
        device_name: str,
    ) -> None:
        super().__init__(name, egu, step_size)
        self._core = core
        self._device_name = device_name

    def set(self, value: float, **_kwargs: Any) -> Status:
        """Move the Z axis by *value* (relative step).

        Parameters
        ----------
        value :
            Step distance in the axis engineering unit.

        Returns
        -------
        Status
            Completes immediately after the hardware call succeeds.
        """
        s = Status()
        try:
            z = self._core.getPosition(self._device_name) + value
            self._core.setPosition(self._device_name, z)
            self.position.set(self.position.get_value() + value)
            s.set_finished()
        except Exception as e:
            s.set_exception(RuntimeError(f"Failed to set Z position: {e}"))
        return s


class MMCoreStageDevice(Device, Loggable):
    """Container device for one or more MMCore stage axes.

    Loads and initialises the hardware via ``CMMCorePlus``, then exposes
    each axis as a typed child attribute (``device.x``, ``device.y``, or
    ``device.z``).  All movement logic lives in the individual axis objects
    ([`MMCoreXYAxis`][] / [`MMCoreZAxis`][]).

    ``read_configuration`` and ``describe_configuration`` aggregate from
    all child axes.

    Parameters
    ----------
    name :
        Identity key of the device.
    config :
        Predefined configuration name (``"demoxy"`` or ``"demoz"``).
    """

    def __init__(self, name: str, /, config: Literal["demoxy", "demoz"] | None) -> None:
        self.config: BaseStageConfig
        match config:
            case "demoxy":
                self.config = DemoXYStageConfig()
            case "demoz":
                self.config = DemoZStageConfig()
            case _:
                err_msg = (
                    f"Unknown stage config: {config}"
                    if config is not None
                    else "Stage config must be specified."
                )
                raise ValueError(err_msg)

        super().__init__(name, **self.config.dump())
        self._core = Core.instance()
        try:
            self._core.loadDevice(self.name, self.config.adapter, self.config.device)
            self._core.initializeDevice(self.name)
        except Exception as e:
            raise RuntimeError(f"Failed to initialize MMCore stage device: {e}") from e

        _axis_list = self.config.axis
        _egu = "um"

        if _axis_list == ["z"]:
            self._core.setOrigin(self.name)
            for ax in _axis_list:
                setattr(
                    self,
                    ax,
                    MMCoreZAxis(
                        name=f"{self.name}-{ax}",
                        egu=_egu,
                        step_size=float(self.config.step_sizes.get(ax, 1.0)),
                        core=self._core,
                        device_name=self.name,
                    ),
                )
        elif _axis_list == ["x", "y"]:
            self._core.setOriginXY(self.name)
            for ax in _axis_list:
                setattr(
                    self,
                    ax,
                    MMCoreXYAxis(
                        name=f"{self.name}-{ax}",
                        egu=_egu,
                        step_size=float(self.config.step_sizes.get(ax, 1.0)),
                        core=self._core,
                        device_name=self.name,
                        axis=ax,
                    ),
                )
        else:
            raise ValueError(
                "Unsupported axis configuration. Only ['x', 'y'] and ['z'] are supported."
            )

    def read_configuration(self) -> dict[str, Reading[Any]]:
        """Aggregate read() from all child axes."""
        result: dict[str, Reading[Any]] = {}
        for _, axis in self.children():
            if isinstance(axis, MotorAxis):
                result.update(axis.read())
        return result

    def describe_configuration(self) -> dict[str, Descriptor]:
        """Aggregate describe() from all child axes."""
        result: dict[str, Descriptor] = {}
        for _, axis in self.children():
            if isinstance(axis, MotorAxis):
                result.update(axis.describe())
        return result

    def prepare(self, _: PrepareInfo) -> Status:
        """No-op: device metadata is forwarded via handle_descriptor_metadata."""
        s = Status()
        s.set_finished()
        return s

    def shutdown(self) -> None:
        self._core.unloadDevice(self.name)
