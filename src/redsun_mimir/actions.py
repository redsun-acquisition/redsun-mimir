from __future__ import annotations

import asyncio
from abc import abstractmethod
from typing import TYPE_CHECKING, ParamSpec, Protocol, TypeVar, cast, runtime_checkable

from bluesky.run_engine import get_bluesky_event_loop

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Sequence

P = ParamSpec("P")
R = TypeVar("R")
R_co = TypeVar("R_co", covariant=True)


def actioned(
    togglable: bool = False,
    pausable: bool = False,
) -> Callable[[Callable[P, R_co]], ActionedPlan[P, R_co]]:
    """Mark a plan as actioned.

    An "actioned" plan informs the view to provide UI elements
    that allow the user to start, stop, pause, and resume the plan execution.

    Parameters
    ----------
    togglable : bool, optional
        Whether the plan is togglable (i.e. an infinite loop that the run engine can stop.)
    pausable : bool, optional
        Whether the plan is pausable (i.e. can be paused and resumed by the run engine.)

    Returns
    -------
    ``Callable[[Callable[P, R_co]], ActionedPlan[P, R_co]]``
        A decorator that marks the plan as actioned.

    Example
    -------
    >>> @actioned(togglable=True, pausable=True)
    >>> def my_plan(
    >>>         detectors: Sequence[DetectorProtocol]
    >>>     ) -> MsgGenerator[None]:
    >>>     ...

    Notes
    -----
    This does not modify the function signature; instead it stores the
    information on the underlying function object (in ``__actions__``),
    to be retrieved later by inspection.
    """

    def decorator(func: Callable[P, R_co]) -> ActionedPlan[P, R_co]:
        setattr(func, "__togglable__", togglable)
        setattr(func, "__pausable__", pausable)

        return cast("ActionedPlan[P, R_co]", func)

    return decorator


@runtime_checkable
class ActionedPlan(Protocol[P, R_co]):
    """
    Plan that has been marked as actioned.

    "Actioned" means that the internal flow of the plan can be influenced
    by external actions, typically triggered by user interaction.

    Used both for static typing (decorator return type) and for runtime checks:

    >>> if isinstance(f, ActionedPlan):
    >>>     print(f.__actions__)

    Attributes
    ----------
    __togglable__ : bool
        Whether the function is togglable (i.e. an infinite loop that the run engine can stop.)
    __pausable__ : bool
        Whether the function is pausable (i.e. can be paused and resumed by the run engine.)

    """

    __togglable__: bool
    __pausable__: bool

    @abstractmethod
    def __call__(  # noqa: D102
        self, *args: P.args, **kwargs: P.kwargs
    ) -> R_co:  # pragma: no cover - protocol
        ...


class ActionList:
    """
    Container type to indicate a set of named actions.

    from typing import Annotated as A

    Example:
        # specify action names via the constructor...
        def my_func(
            detectors: Sequence[DetectorProtocol],
            actions: A[Sequence[str], ActionList(names=["do_this", "do_that"])]
        ) -> None:
            ...

        # ...or via default argument values
        def my_func(
            detectors: Sequence[DetectorProtocol],
            actions: A[Sequence[str], ActionList()] = ["do_this", "do_that"]
        ) -> None:

    Parameters
    ----------
    names : list[str] | None, optional
        The list of action names.
        If None or not provided, defaults to an empty list.
    """

    names: list[str]

    def __init__(self, names: list[str] | None = None) -> None:
        self.names = names or []


#: Dictionary to hold named asyncio.Events to manage plan actions.
_events: dict[str, asyncio.Event] = {}


def create_events(names: str | Sequence[str]) -> dict[str, asyncio.Event]:
    """Create one or multiple asyncio.Event by name.

    Coroutines are executed within the Bluesky event loop.

    Parameters
    ----------
    names: str | Sequence[str]
        The name(s) of the event(s) to create.

    Returns
    -------
    dict[str, asyncio.Event]
        A dictionary mapping event names to the created asyncio.Event objects.
    """

    async def _create_events(names: Sequence[str]) -> dict[str, asyncio.Event]:
        global _events
        new_events = {name: asyncio.Event() for name in names if name not in _events}
        _events.update(new_events)
        return new_events

    loop = get_bluesky_event_loop()
    names = [names] if isinstance(names, str) else names
    new_events = asyncio.run_coroutine_threadsafe(_create_events(names), loop).result()
    return new_events


def set_events(names: str | Sequence[str]) -> None:
    """Set one or multiple asyncio.Event by name.

    Coroutines are executed within the Bluesky event loop.

    Parameters
    ----------
    names: str | Sequence[str]
        The name(s) of the event(s) to set.
    """

    async def _set_events(names: Sequence[str]) -> None:
        global _events
        for name in names:
            event = _events.get(name)
            if event:
                event.set()

    loop = get_bluesky_event_loop()
    names = [names] if isinstance(names, str) else names
    asyncio.run_coroutine_threadsafe(_set_events(names), loop).result()


def clear_events(names: str | Sequence[str]) -> None:
    """Clear an asyncio.Event by name.

    Coroutines are executed within the Bluesky event loop.

    Parameters
    ----------
    name: str | Sequence[str]
        The name(s) of the event(s) to clear.
    """

    async def _clear_events(names: Sequence[str]) -> None:
        global _events
        for name in names:
            event = _events.get(name)
            if event:
                event.clear()

    loop = get_bluesky_event_loop()
    names = [names] if isinstance(names, str) else names
    asyncio.run_coroutine_threadsafe(_clear_events(names), loop).result()


def get_events() -> dict[str, asyncio.Event]:
    """Return the currently managed events."""
    global _events
    return _events


def delete_events() -> None:
    """Delete all currently managed events.

    All events are cleared and the internal event dictionary is reset.
    """
    global _events

    async def _clear_all() -> None:
        global _events
        _events.clear()
        _events = {}

    loop = get_bluesky_event_loop()
    asyncio.run_coroutine_threadsafe(_clear_all(), loop).result()


__all__ = [
    "actioned",
    "create_events",
    "set_events",
    "clear_events",
    "delete_events",
    "get_events",
]
