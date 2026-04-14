from __future__ import annotations

from typing import TYPE_CHECKING

from pymmcore_plus import CMMCorePlus as Core
from redsun.device import Device
from redsun.engine import Status
from redsun.log import Loggable
from redsun.utils.descriptors import (
    parse_key,
)

from redsun_mimir.device.axis import MotorAxis
from redsun_mimir.device.mmcore.configs import (
    BaseStageConfig,
    DemoXYStageConfig,
    DemoZStageConfig,
)
from redsun_mimir.protocols import MotorProtocol

if TYPE_CHECKING:
    from typing import Any, Literal

    from bluesky.protocols import Descriptor, Location, Reading
    from redsun.storage import PrepareInfo


class MMCoreStageDevice(Device, MotorProtocol, Loggable):
    """Device control for a Micro-Manager stage.

    Parameters
    ----------
    name : str
        Identity key of the device.
    config : Literal["demoxy", "demoz"], optional
        Predefined configuration for the stage device.
    """

    _stage_type: Literal["XY", "Z"]

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
        if _axis_list == ["Z"]:
            self._core.setOrigin(self.name)
            self._stage_type = "Z"
        elif _axis_list == ["X", "Y"]:
            self._core.setOriginXY(self.name)
            self._stage_type = "XY"
        else:
            raise ValueError(
                "Unsupported axis configuration. Only ['X', 'Y'] and ['Z'] are supported."
            )

        _egu = "um"
        # Build MotorAxis children.  The key prefix is "{device_name}-{axis_name}"
        # so that read()/describe() produce canonical keys that group correctly
        # in the view layer via parse_key().
        self.axes: dict[str, MotorAxis] = {
            ax: MotorAxis(
                name=f"{self.name}-{ax}",
                egu=_egu,
                step_size=float(self.config.step_sizes.get(ax, 1.0)),
            )
            for ax in _axis_list
        }
        self._active_axis: str = _axis_list[0]

    def set(self, value: Any, **kwargs: Any) -> Status:
        """Set something in the stage device."""
        s = Status()
        raw = kwargs.get("propr", None) or kwargs.get("prop", None)
        if raw is not None:
            # Accept either a canonical key ("name-property") or a bare name
            try:
                _, propr = parse_key(str(raw))
            except ValueError:
                propr = str(raw)
            self.logger.info("Setting property %s to %s.", propr, value)
            if propr == "axis" and isinstance(value, str):
                self._active_axis = value
                s.set_finished()
                return s
            elif propr == "step_size" and isinstance(value, int | float):
                # bare "step_size" updates the currently active axis
                self.axes[self._active_axis].step_size.set(float(value))
                s.set_finished()
                return s
            elif propr.endswith("-step_size") and isinstance(value, int | float):
                # axis-qualified form: "{ax}-step_size" (e.g. "X-step_size")
                ax = propr.removesuffix("-step_size")
                if ax in self.axes:
                    self.axes[ax].step_size.set(float(value))
                    s.set_finished()
                    return s
                s.set_exception(ValueError(f"Unknown axis in property: {propr}"))
                return s
            else:
                s.set_exception(ValueError(f"Invalid property: {propr}"))
                return s
        else:
            if not isinstance(value, int | float):
                s.set_exception(TypeError(f"Expected float, got {type(value)}"))
                return s

        axis = self._active_axis
        current_pos = self.axes[axis].position.get_value()
        new_pos = current_pos + float(value)
        try:
            match self._stage_type:
                case "Z":
                    z = self._core.getPosition(self.name) + value
                    self._core.setPosition(self.name, z)
                case "XY":
                    positions = self._core.getXYPosition(self.name)
                    x = positions[0]
                    y = positions[1]
                    if axis == "X":
                        x = x + value
                    elif axis == "Y":
                        y = y + value
                    self._core.setXYPosition(self.name, x, y)
                case _:
                    s.set_exception(  # type: ignore[unreachable]
                        RuntimeError(f"Unsupported stage type: {self._stage_type}")
                    )
        except Exception as e:
            s.set_exception(RuntimeError(f"Failed to set position: {e}"))
            return s

        # update position tracking on the MotorAxis
        self.axes[axis].position.set(new_pos)
        s.add_callback(self._update_readback)
        s.set_finished()
        return s

    def locate(self) -> Location[float]:
        """Locate the active axis position."""
        pos = self.axes[self._active_axis].position.get_value()
        return {"setpoint": pos, "readback": pos}

    def read_configuration(self) -> dict[str, Reading[Any]]:
        result: dict[str, Reading[Any]] = {}
        for axis in self.axes.values():
            result.update(axis.read())
        return result

    def describe_configuration(self) -> dict[str, Descriptor]:
        result: dict[str, Descriptor] = {}
        for axis in self.axes.values():
            result.update(axis.describe())
        return result

    def prepare(self, _: PrepareInfo) -> Status:
        """No-op: device metadata is forwarded via handle_descriptor_metadata."""
        s = Status()
        s.set_finished()
        return s

    def shutdown(self) -> None:
        self._core.unloadDevice(self.name)

    def _update_readback(self, status: Status) -> None:
        """No-op callback kept for bluesky compatibility.

        Position is already stored on the ``MotorAxis`` via ``set()``;
        the readback is not tracked separately.
        """
