from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sunflare.engine import Status

from redsun_mimir.protocols import LightProtocol, MotorProtocol

from ._core import Factory, Stage, XYStage

if TYPE_CHECKING:
    from concurrent.futures import Future
    from typing import Optional, Union

    from bluesky.protocols import Descriptor, Location, Reading

    from .._config import LightModelInfo, StageModelInfo
    from ._core import Intensity


class OWFSLight(LightProtocol):
    def __init__(self, name: str, model_info: LightModelInfo) -> None:
        if model_info.binary:
            raise ValueError("Binary light sources are not supported.")
        self._name = name
        self._model_info = model_info
        self._light_ctrl: Intensity
        self.intensity = model_info.intensity_range[0]
        self.enabled = False

        def callback(fut: Future[Intensity]) -> None:
            self._light_ctrl = fut.result()

        self.fut: Future[Intensity] = Factory(device_type="light")
        self.fut.add_done_callback(callback)

    def trigger(self) -> Status:
        s = Status()
        self._light_ctrl.open = not self._light_ctrl.open
        s.set_finished()
        return s

    def set(self, value: Any, **kwargs: Any) -> Status:
        s = Status()
        if not isinstance(value, (int, float)):
            raise ValueError("Value must be a number.")
        self._light_ctrl.intensity = float(value)
        s.set_finished()
        return s

    @property
    def name(self) -> str:
        return self._name

    @property
    def model_info(self) -> LightModelInfo:
        return self._model_info

    @property
    def parent(self) -> None:
        return None


class OWFSStage(MotorProtocol):
    def __init__(self, name: str, model_info: StageModelInfo) -> None:
        if len(model_info.axis) not in [1, 2]:
            raise ValueError("Only single and dual axis stages are supported.")
        if len(model_info.axis) == 1 and model_info.axis[0].lower() != "z":
            raise ValueError("Single axis stages must be Z stages (use 'z' or 'Z').")
        if len(model_info.axis) == 2 and (
            model_info.axis[0].lower() != "x" or model_info.axis[1].lower() != "y"
        ):
            raise ValueError("Dual axis stages must be XY stages (use 'x' and 'y').")

        self._name = name
        self._model_info = model_info

        self._stage_ctrl: Union[Stage, XYStage]

        if len(model_info.axis) == 1:

            def callback_z(fut: Future[Stage]) -> None:
                self._stage_ctrl = fut.result()

            kwargs = {
                "step_z": model_info.step_sizes[model_info.axis[0]],
                "egu_z": model_info.egu,
            }
            self.future = Factory(device_type="z_stage", **kwargs)
            self.future.add_done_callback(callback_z)
        else:

            def callback_xy(fut: Future[XYStage]) -> None:
                self._stage_ctrl = fut.result()

            step_x = model_info.step_sizes[
                next(ax for ax in model_info.axis if ax.lower() == "x")
            ]
            step_y = model_info.step_sizes[
                next(ax for ax in model_info.axis if ax.lower() == "y")
            ]

            kwargs = {
                "step_x": step_x,
                "step_y": step_y,
                "egu_x": model_info.egu,
                "egu_y": model_info.egu,
            }

            self.future = Factory(device_type="xy_stage", **kwargs)
            self.future.add_done_callback(callback_xy)

        # set the current axis to the first axis;
        # it will be updated anyway via "set"
        self.axis = model_info.axis[0]

    def set(self, value: Any, **kwargs: Any) -> Status:
        """Set something in the model.

        Either set the motor position or update a configuration value.
        When setting a configuration value, the keyword argument `prop`
        must be provided.
        Accepted updatable properties:

        - ``axis``: motor axis.

        i.e. `set(10)` will set the motor position to 10,
        `set("Y", prop="axis")` will update the axis to "Y".

        Parameters
        ----------
        value : ``Any``
            New value to set.
        **kwargs : ``Any``
            Additional keyword arguments.

        Returns
        -------
        ``Status``
            The status object.
            For this mock model, it will always be set to finished.
            If ``value`` is not of type ``float``,
            the status will set a ``ValueError`` exception.

        """
        s = Status()
        axis: Optional[str] = kwargs.get("prop", None)
        if axis is not None:
            axis = str(axis)
            if axis not in self._model_info.axis:
                s.set_exception(
                    ValueError("Incorrect axis specified (received {}).".format(axis))
                )
                return s
            else:
                self.axis = axis
                s.set_finished()
                return s
        else:
            if not isinstance(value, (int, float)):
                s.set_exception(ValueError("Value must be a number."))
                return s
        if self.axis.lower() == "z":
            assert isinstance(self._stage_ctrl, Stage)
            self._stage_ctrl.position = value
        else:
            assert isinstance(self._stage_ctrl, XYStage)
            if self.axis.lower() == "x":
                self._stage_ctrl.x = value
            else:
                self._stage_ctrl.y = value
        s.set_finished()
        return s

    def locate(self) -> Location[Any]:
        if isinstance(self._stage_ctrl, Stage):
            return {
                "setpoint": self._stage_ctrl.position,
                "readback": self._stage_ctrl.position,
            }
        else:
            setpoint = (
                self._stage_ctrl.x if self.axis.lower() == "x" else self._stage_ctrl.y
            )
            readback = setpoint
            return {"setpoint": setpoint, "readback": readback}

    def read_configuration(self) -> dict[str, Reading[Any]]:
        """Read mock configuration."""
        return self.model_info.read_configuration()

    def describe_configuration(self) -> dict[str, Descriptor]:
        """Describe mock configuration."""
        return self.model_info.describe_configuration()

    @property
    def name(self) -> str:
        return self._name

    @property
    def model_info(self) -> StageModelInfo:
        return self._model_info

    @property
    def parent(self) -> None:
        return None
