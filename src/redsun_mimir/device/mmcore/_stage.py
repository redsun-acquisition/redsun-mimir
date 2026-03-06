from __future__ import annotations

import time
from typing import TYPE_CHECKING

from pymmcore_plus import CMMCorePlus as Core
from redsun.device import Device
from redsun.engine import Status
from redsun.log import Loggable
from redsun.storage.metadata import register_metadata
from redsun.utils.descriptors import (
    make_descriptor,
    make_key,
    make_reading,
    parse_key,
)

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
                if config is None:
                    raise ValueError("Stage config must be specified.")
                else:
                    raise ValueError(f"Unknown stage config: {config}")

        super().__init__(name, **self.config.dump())
        self._core = Core.instance()
        try:
            self._core.loadDevice(self.name, self.config.adapter, self.config.device)
            self._core.initializeDevice(self.name)
        except Exception as e:
            raise RuntimeError(f"Failed to initialize MMCore stage device: {e}") from e
        # would be nice to recover the origin from
        # a previous session, but i'm not sure there's
        # a way to cache that reliably; might be worth
        # to ask the pymmcore-plus developers
        self.axis = self.config.axis
        if self.axis == ["Z"]:
            self._core.setOrigin(self.name)
            self._stage_type = "Z"
        elif self.axis == ["X", "Y"]:
            self._core.setOriginXY(self.name)
            self._stage_type = "XY"
        else:
            raise ValueError(
                "Unsupported axis configuration. Only ['X', 'Y'] and ['Z'] are supported."
            )
        self.egu = "um"
        self._positions: dict[str, Location[float]] = {
            axis: {"setpoint": 0.0, "readback": 0.0} for axis in self.axis
        }
        # TODO: how to retrieve this information from the device?
        # if it is available at all?
        self.step_sizes = self.config.step_sizes
        self._active_axis = self.axis[0]

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
                self.step_sizes[self._active_axis] = value
                s.set_finished()
                return s
            elif propr.endswith("_step_size") and isinstance(value, int | float):
                # axis-qualified form: "{ax}_step_size" (e.g. "X_step_size")
                ax = propr[: -len("_step_size")]
                if ax in self.step_sizes:
                    self.step_sizes[ax] = value
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
        self._positions[self._active_axis]["setpoint"] += value
        s.add_callback(self._update_readback)
        s.set_finished()
        return s

    def locate(self) -> Location[float]:
        """Locate the active axis position."""
        return self._positions[self._active_axis]

    def read_configuration(self) -> dict[str, Reading[Any]]:
        timestamp = time.time()
        config: dict[str, Reading[Any]] = {
            make_key(self.name, "egu"): make_reading(self.egu, timestamp),
            make_key(self.name, "axis"): make_reading(self.axis, timestamp),
        }
        for ax, step in self.step_sizes.items():
            config[make_key(self.name, f"{ax}_step_size")] = make_reading(
                step, timestamp
            )
        return config

    def describe_configuration(self) -> dict[str, Descriptor]:
        descriptors: dict[str, Descriptor] = {
            make_key(self.name, "egu"): make_descriptor(
                "settings", "string", readonly=True
            ),
            make_key(self.name, "axis"): make_descriptor(
                "settings", "array", shape=[len(self.axis)], readonly=True
            ),
        }
        for ax in self.axis:
            key = make_key(self.name, f"{ax}_step_size")
            descriptors[key] = make_descriptor("settings", "number")
        return descriptors

    def prepare(self, _: PrepareInfo) -> Status:
        """Contribute motor metadata to the acquisition metadata registry."""
        s = Status()
        md: dict[str, Any] = {}
        md.update({"motor_egu": self.egu})
        for axis in self.axis:
            md.update({f"position_{axis.lower()}": self._positions[axis]["readback"]})
            md.update({f"step_size_{axis.lower()}": self.step_sizes[axis]})
        register_metadata(self.name, md)
        s.set_finished()
        return s

    def shutdown(self) -> None:
        self._core.unloadDevice(self.name)

    def _update_readback(self, status: Status) -> None:
        """Update the currently active axis readback position.

        When the status object is set as finished successfully,
        the readback position is updated to match the setpoint.

        Parameters
        ----------
        s : Status
            The status object associated with the callback.
        """
        if status.success:
            self._positions[self._active_axis]["readback"] = self._positions[
                self._active_axis
            ]["setpoint"]
