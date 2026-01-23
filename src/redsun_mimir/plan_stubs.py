from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import bluesky.plan_stubs as bps
from bluesky.utils import Msg

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from typing import Any, Final, Literal

    from bluesky.protocols import Movable, Readable, Status
    from bluesky.utils import MsgGenerator

    from redsun_mimir.actions import SRLatch
    from redsun_mimir.protocols import ReadableFlyer

SIXTY_FPS: Final[float] = 1.0 / 60.0


def set_property(
    obj: Movable[Any],
    value: Any,
    /,
    propr: str,
    timeout: float | None = None,
) -> MsgGenerator[Status]:
    """Set a property of a `Movable` object and wait for completion.

    Parameters
    ----------
    obj: Movable[Any]
        The Movable object to set.
    value: Any
        The value to set the property to.
    propr: str, keyword-only
        The property name to set.
    timeout: float, keyword-only, optional
        The maximum time (in seconds) to wait for the operation to complete.
        Default is None (wait indefinitely).

    Yields
    ------
    Msg
        Yields two messages:
        - `Msg("set", obj, value, propr=propr)`: to set the property.
        - `Msg("wait", None, timeout=timeout)`: to wait for the operation to complete.

    Returns
    -------
    Status
        The status object returned by the `set` method.
    """
    group = str(uuid.uuid4())
    status: Status = yield Msg("set", obj, value, group=group, propr=propr)
    yield Msg("wait", None, group=group, timeout=timeout)
    return status


def wait_for_actions(
    events: Mapping[str, SRLatch],
    timeout: float = 0.001,
    wait_for: Literal["set", "reset"] = "set",
) -> MsgGenerator[tuple[str, SRLatch] | None]:
    """Wait for any of the given input latches to be set or reset.

    Plan execution will be blocked until one of the latches changes state; but
    background tasks will proceed as usual.

    Parameters
    ----------
    events: Mapping[str, SRLatch]
        A mapping of event names to SRLatch objects to wait for.

    timeout: float, optional
        The maximum time (in seconds) to wait for a latch to change state.
        Default is 0.001 seconds.

    wait_for: Literal["set", "reset"], optional
        Whether to wait for the latch to be set or reset.
        Default is "set".

    Returns
    -------
    tuple[str, SRLatch] | None
        A tuple containing the name and latch that changed state to unblock the plan;
        None if timeout occurred before any latch changed state.
    """
    ret: tuple[str, SRLatch] | None = yield Msg(
        "wait_for_actions", None, events, timeout=timeout, wait_for=wait_for
    )
    return ret


def read_while_waiting(
    objs: Sequence[Readable[Any]],
    events: Mapping[str, SRLatch],
    stream_name: str = "primary",
    refresh_period: float = SIXTY_FPS,
    wait_for: Literal["set", "reset"] = "set",
) -> MsgGenerator[tuple[str, SRLatch]]:
    """Read a list of `Readable` objects while waiting for actions.

    Parameters
    ----------
    objs : ``Sequence[Readable[Any]]``
        The objects to trigger and read.
    events : ``Mapping[str, SRLatch]``
        A mapping of event names to SRLatch objects to wait for.
        Each latch represents an action that can unblock the plan.
    stream_name : ``str``, optional
        The name of the stream to collect data into.
        Default is "primary".
    refresh_period : ``float``, optional
        The period (in seconds) to refresh the triggering and reading.
        Default is 60 Hz (1/60 s).
    wait_for : ``Literal["set", "reset"]``, optional
        Whether to wait for the latch to be set or reset.
        Default is "set".

    Yields
    ------
    Msg
        Messages to wait and trigger/read the objects.

    Returns
    -------
    tuple[str, SRLatch]
        The latch that changed state to unblock the plan.
    """
    event: tuple[str, SRLatch] | None = None
    while event is None:
        yield from bps.checkpoint()
        event = yield from wait_for_actions(
            events, timeout=refresh_period, wait_for=wait_for
        )
        yield from bps.trigger_and_read(objs, name=stream_name)
    return event


def read_while_completing(
    objs: Sequence[ReadableFlyer],
    stream_name: str = "primary",
    refresh_period: float = SIXTY_FPS,
) -> MsgGenerator[None]:
    """Instruct a sequence of objects to complete() the operation.

    While waiting for the completion, periodically trigger and read the objects,
    until one of the given latches is reset.

    Parameters
    ----------
    objs : ``Sequence[ReadableFlyer]``
        The objects to complete.
    events : ``Mapping[str, SRLatch]``
        A mapping of event names to SRLatch objects to wait for.
        Each latch represents an action that can unblock the plan.
    refresh_period : ``float``, optional
        The period (in seconds) to refresh the waiting.

    Returns
    -------
    tuple[str, SRLatch]
        The latch that changed state to unblock the plan.
    """
    group = str(uuid.uuid4())
    yield from bps.complete_all(*objs, group=group, wait=False)
    done = False
    while not done:
        done = bps.wait(group=group, timeout=refresh_period)
        yield from bps.trigger_and_read(objs, name=stream_name)
