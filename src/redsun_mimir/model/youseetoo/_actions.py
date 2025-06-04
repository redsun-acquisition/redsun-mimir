from __future__ import annotations

import re

from msgspec import UNSET, Struct, UnsetType, field


def _tag_action(class_name: str) -> str:
    """Create a tag field for the specific action.

    The function output depends on the class name which
    subclasses the `_Action` struct.
    The final tag field will be formatted as
    `/<action-name>_act`, where `<action-name>` is the
    lowercase version of the class name, with the
    `_Action` suffix removed and replaced with `_act`.

    i.e.

    .. code-block:: python

        class LaserAction(_Action):
            pass


        tag_name = _tag_action(LaserAction.__name__)
        # tag_name will be "/laser_act"

    The `tag` field is automatically generated
    when subclassing the `_Action` struct.

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


def tag_response(class_name: str) -> str:
    """Convert a camel case class name to a snake case tag.

    Any additional underscores in the class name
    are removed, and the class name is converted to
    snake case.


    Parameters
    ----------
    name: `str`
        Camel case class name to convert.

    Returns
    -------
    `str`
        Snake case class name.

    Examples
    --------
    >>> camel_to_snake("_ActionResponse")
    'action_response'
    >>> camel_to_snake("_MotorActionResponse")
    'motor_action_response'
    """
    # Find all capital letters, and add an underscore before them
    # The lookahead (?=[A-Z]) ensures we don't add underscore after the last match
    intermediate = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", class_name)
    # Handle consecutive capital letters (like "API")
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", intermediate).lower()


class _Action(Struct, tag_field="task", tag=_tag_action):
    """Base struct for Mimir actions.

    Automatically generates a `task` tag field
    based on the class name.
    """


class Acknowledge(Struct):
    """Mimir response message.

    Common response structure for Mimir actions,
    regardless of the specific action type.

    Provides a way to acknowledge the action
    and its success status.

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

    qid: int | UnsetType
    success: int = field(default=1)


class LaserAction(_Action):
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
        Defaults to 3000 (3,000 steps/s).
    accel: `int`
        Acceleration of the stepper motor (steps/s²).
        Defaults to 10000 (10,000 steps/s²).
    isabs: `int`
        Flag indicating if the position is absolute (1) or relative (0).
        Defaults to 0 (relative position).
    isaccel: `int`
        Flag whether acceleration ramping should be applied at the beginning of the movement (1) or not (0).
        Defaults to 0.
    isforever: `int`, optional
        Currently unused. Defaults to `UNSET`.
    """

    id: int = field(name="stepperid")
    position: int
    speed: int = field(default=3000)
    accel: int = field(default=10000)
    isabs: int = field(default=0)
    isaccel: int = field(default=0)
    isforever: int | UnsetType = field(default=UNSET)


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


class MotorAction(_Action):
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


class MovementResponseInfo(Struct):
    """Information about a movement response.

    Attributes
    ----------
    id: `int`
        ID of the stepper motor.
        Encoded name will be `stepperid`.
    position: `int`
        Current position of the stepper motor.
    done: `int`
        Flag indicating if the movement is done.
        Currently, the API will always return 0.
        Requires clarification from UC2 team.
    """

    id: int = field(name="stepperid")
    position: int
    done: int = field(name="isDone")


class MotorResponse(Struct):
    """Response for a motor action.

    This response is followed after the confirmation that
    `Acknowledge` has been received; it details the
    success of the motor movement.

    Attributes
    ----------
    steppers: `list[MovementResponseInfo]`
        List of movement responses for each stepper motor.
        Each response is described by the `MovementResponseInfo` struct.
    qid: `int`
        UC2 queue ID of the requested action.
        Must match the `qid` in the `MotorAction` request.
    """

    steppers: list[MovementResponseInfo]
    qid: int
