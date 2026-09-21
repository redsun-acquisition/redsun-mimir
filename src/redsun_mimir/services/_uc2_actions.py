from __future__ import annotations

import re

from msgspec import UNSET, Struct, UnsetType, field


def _tag_action(class_name: str) -> str:
    """Return the `task` tag of an `_Action` subclass, `/<name>_act`.

    *class_name* is lowercased and its `Action` suffix replaced by `_act`, so
    `LaserAction` tags as `/laser_act`.
    """
    return "".join(["/", class_name.lower().replace("action", "_act")])


def tag_response(class_name: str) -> str:
    """Convert a camel case class name to a snake case tag.

    `MotorActionResponse` gives `motor_action_response`.
    """
    # Find all capital letters, and add an underscore before them
    # The lookahead (?=[A-Z]) ensures we don't add underscore after the last match
    intermediate = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", class_name)
    # Handle consecutive capital letters (like "API")
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", intermediate).lower()


class _Action(Struct, tag_field="task", tag=_tag_action):
    """Base struct for an action, its `task` tag derived from the class name."""


class Acknowledge(Struct):
    """The board's response to any action.

    Attributes
    ----------
    qid: `int`
        Queue id of the action, matching the request's.
    success: `int`
        1 on success, -1 on failure.
    """

    qid: int | UnsetType
    success: int = field(default=1)


class LaserAction(_Action):
    """A laser action.

    Attributes
    ----------
    id: `int`
        Laser id, 0 to 3, encoded as `LASERid`.
    value: `int`
        Value commanded, encoded as `LASERval`.
    qid: `int`, optional
        Queue id tracking the command.
    """

    id: int = field(name="LASERid")
    value: int = field(name="LASERval")
    qid: int | UnsetType = field(default=UNSET)


class MovementInfo(Struct):
    """One stepper motor's movement.

    Attributes
    ----------
    id: `int`
        Stepper id, encoded as `stepperid`.
    position: `int`
        Target position.
    speed: `int`
        Steps per second.
    accel: `int`
        Steps per second squared.
    isabs: `int`
        1 for an absolute position, 0 for a relative one.
    isaccel: `int`
        1 to ramp the acceleration at the start of the movement, 0 not to.
    isforever: `int`, optional
        Unused.
    """

    id: int = field(name="stepperid")
    position: int
    speed: int = field(default=10_000)
    accel: int = field(default=10_000)
    isabs: int = field(default=1)
    isaccel: int = field(default=0)
    isforever: int | UnsetType = field(default=UNSET)


class Movement(Struct):
    """The movements a motor action performs, one `MovementInfo` each."""

    steppers: list[MovementInfo]

    @classmethod
    def generate_info(cls, id: int, position: int) -> Movement:
        """Return a `Movement` of one `MovementInfo`: stepper *id* to *position*."""
        return cls(steppers=[MovementInfo(id=id, position=position)])


class MotorAction(_Action):
    """A stage action.

    Attributes
    ----------
    movement: `Movement`
        The movements to perform, encoded as `motor`.
    qid: `int`, optional
        Queue id tracking the command.
    """

    movement: Movement = field(name="motor")
    qid: int | UnsetType = field(default=UNSET)

    @classmethod
    def generate_movement(
        cls,
        id: int,
        position: int,
    ) -> Movement:
        """Return a `Movement` of one stepper, *id* to *position*."""
        return Movement.generate_info(
            id=id,
            position=position,
        )


class MovementResponseInfo(Struct):
    """One stepper motor's state in a motor response.

    Attributes
    ----------
    id: `int`
        Stepper id, encoded as `stepperid`.
    position: `int`
        Current position.
    done: `int`
        Whether the movement is done; the board always answers 0.
    """

    id: int = field(name="stepperid")
    position: int
    done: int = field(name="isDone")


class MotorResponse(Struct):
    """The board's report on a motor action, sent after its `Acknowledge`.

    Attributes
    ----------
    steppers: `list[MovementResponseInfo]`
        One entry per stepper moved.
    qid: `int`
        Queue id, matching the `MotorAction` request's.
    """

    steppers: list[MovementResponseInfo]
    qid: int
