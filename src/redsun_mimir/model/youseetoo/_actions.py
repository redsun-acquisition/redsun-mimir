from __future__ import annotations

from msgspec import UNSET, Struct, UnsetType, field


def _tag_action(class_name: str) -> str:
    """Create a tag field for the specific action.

    The function output depends on the class name which
    subclasses the `Action` struct.
    The final tag field will be formatted as
    `/<action-name>_act`, where `<action-name>` is the
    lowercase version of the class name, with the
    `Action` suffix removed and replaced with `_act`.

    i.e.

    .. code-block:: python

        class LaserAction(Action):
            pass


        tag_name = _tag_action(LaserAction.__name__)
        # tag_name will be "/laser_act"

    The `tag` field is automatically generated
    when subclassing the `Action` struct.

    Parameters
    ----------
    class_name: `str`
        Class name to convert.

    Returns
    -------
    `str`
        Converted command name.
    """
    return "".join(["/", class_name.lower().replace("action", "_act")])


class Action(Struct, tag_field="task", tag=_tag_action):
    """Base struct for Mimir actions.

    Automatically generates a `task` tag field
    based on the class name.
    """


class ActionResponse(Struct):
    """Mimir response message.

    Common response structure for Mimir actions,
    regardless of the specific action type.

    Attributes
    ----------
    qid: `int`
        UC2 queue ID of the requested action.
        Must match the `qid` in the request.
    success: `int`
        The success status of the action.
        1: success, -1: failure.
        Defaults to 1 (assuming success).
    """

    qid: int
    success: int = field(default=1)


class LaserAction(Action):
    """Mimir light action message.

    Attributes
    ----------
    id: `int`
        ID of the laser command (ranging from 0 to 3).
        Encoded name will be `LASERid`.
    value: int
        Value of the command.
        Encoded name will be `LASERval`.
    qid: `int`, optional
        UC2 queue ID for tracking the command.
    """

    id: int = field(name="LASERid")
    value: int = field(name="LASERval")
    qid: int | UnsetType = field(default=UNSET)


class MovementInfo(Struct):
    """Information about a movement of a specific stepper motor.

    Attributes
    ----------
    id: `int`
        ID of the stepper motor.
        Encoded name will be `stepperid`.
    position: `int`
        Target position of the stepper motor.
    speed: `int`
        Speed of the stepper motor (steps/s).
    accel: `int`
        Acceleration of the stepper motor (steps/s²).
        Defaults to 10000 (10,000 steps/s²).
    isabs: `int`
        Flag indicating if the position is absolute (1) or relative (0).
        Defaults to 0 (relative position).
    isaccel: `int`
        Flag whether acceleration ramping should be applied at the beginning of the movement (1) or not (0).
        Defaults to 1.
    isforever: `int`
        Flag indicating if the movement should be continous (1) or not (0).
        Defaults to 1 (continous movement).
    """

    id: int = field(name="stepperid")
    position: int
    speed: int
    accel: int = field(default=10000)
    isabs: int = field(default=0)
    isaccel: int = field(default=1)
    isforever: int = field(default=1)


class Movement(Struct):
    """Container for a list of movements to perform.

    Attributes
    ----------
    steppers: `list[MovementInfo]`
        List of movements to perform.
        Each movement is described by the `MovementInfo` struct.
    """

    steppers: list[MovementInfo]

    @classmethod
    def generate_info(cls, id: int, position: int) -> Movement:
        """Generate a `Movement` struct with a single `MovementInfo`.

        Parameters
        ----------
        id: `int`
            ID of the stepper motor.
        position: `int`
            Target position of the stepper motor.

        Returns
        -------
        `Movement`
            A `Movement` struct with a single `MovementInfo`.
        """
        return cls(steppers=[MovementInfo(id=id, position=position)])


class MotorAction(Action):
    """Mimir stage action message.

    Attributes
    ----------
    qid: `int`, optional
        UC2 queue ID for tracking the command.
    movement: `Movement`
        Movement information for the stepper motor.
        Encoded name will be `motor`.
    """

    movement: Movement = field(name="motor")
    qid: int | UnsetType = field(default=UNSET)

    @classmethod
    def generate_movement(
        cls,
        id: int,
        position: int,
    ) -> Movement:
        """Generate a `MotorAction` based on input information.

        Parameters
        ----------
        id: `int`
            ID of the stepper motor.
        position: `int`
            Target position of the stepper motor.

        Returns
        -------
        `Movement`
            A `Movement` struct.
        """
        return Movement.generate_info(
            id=id,
            position=position,
        )
