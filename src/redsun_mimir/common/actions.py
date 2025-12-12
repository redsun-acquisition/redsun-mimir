from __future__ import annotations

import asyncio
from abc import abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, ParamSpec, Protocol, TypeVar, cast, runtime_checkable

from bluesky.run_engine import get_bluesky_event_loop

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Sequence
    from typing import Any, Literal, TypeAlias

    CoroutineOp: TypeAlias = Literal["create", "set", "clear"]
    EventCoroutine: TypeAlias = Callable[[str], Coroutine[Any, Any, None]]

P = ParamSpec("P")
R = TypeVar("R")
R_co = TypeVar("R_co", covariant=True)

__all__ = ["Actions", "ActionManager", "actioned", "create"]


def actioned(
    togglable: bool = False,
    pausable: bool = False,
) -> Callable[[Callable[P, R_co]], ActionedPlan[P, R_co]]:
    """Attach action names to parameters typed as `Actions`.

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
    __actions__ : Mapping[str, Actions]
        Mapping of parameter names to Actions instances,
        indicating which parameters are associated with which actions.

    """

    __togglable__: bool
    __pausable__: bool

    @abstractmethod
    def __call__(
        self, *args: P.args, **kwargs: P.kwargs
    ) -> R_co:  # pragma: no cover - protocol
        ...


@dataclass
class Actions:
    """
    Container type to indicate a set of named actions.

    Example:
        def my_func(
            detectors: Sequence[DetectorProtocol],
            events: Actions = Actions(names=["stop", "pause"]),
        ) -> None:
            ...

    If a parameter is annotated as `Actions` but has no default value, no
    UI elements will be generated for it.
    """

    names: list[str]


class ActionManager:
    """Creates and manages asyncio.Event objects.

    These are created within the Bluesky event loop,
    and are used to communicate with plans running in the RunEngine.
    """

    events_op: dict[CoroutineOp, EventCoroutine]
    _events: dict[str, asyncio.Event]

    def __init__(self) -> None:
        self._events = {}
        self._events_op = {
            "create": self._create_event,
            "set": self._set_event,
            "clear": self._clear_event,
        }
        self._bluesky_loop: asyncio.AbstractEventLoop = get_bluesky_event_loop()
        assert self._bluesky_loop is not None

    async def _create_event(self, name: str) -> None:
        """Create an asyncio.Event with the given name.

        The event is bound to the Bluesky event loop
        running in the background thread of the RunEngine.
        """
        self._events[name] = asyncio.Event()

    async def _set_event(self, name: str) -> None:
        """Set an existing asyncio.Event with the given name."""
        event = self._events.get(name)
        if event is not None:
            event.set()

    async def _clear_event(self, name: str) -> None:
        """Clear an existing asyncio.Event with the given name."""
        event = self._events.get(name)
        if event is not None:
            event.clear()

    def manage_event(self, name: str, op: Literal["create", "set", "clear"]) -> None:
        """Create, set, or clear an asyncio.Event by name.

        Coroutines are executed within the Bluesky event loop.

        Parameters
        ----------
        name: str
            The name of the event to manage.
        op: Literal["create", "set", "clear"]
            The operation to perform on the event.
        """
        future = asyncio.run_coroutine_threadsafe(
            self._events_op[op](name), self._bluesky_loop
        )
        future.result()  # Wait for completion

    @property
    def events(self) -> dict[str, asyncio.Event]:
        """Return the list of managed events."""
        return self._events


def create(
    names: Sequence[str], manager: ActionManager | None
) -> dict[str, asyncio.Event]:
    """Create multiple asyncio.Event objects by their names.

    Parameters
    ----------
    names: Sequence[str]
        The names of the events to create.
    manager: ActionManager | None
        An optional ActionManager instance to use for managing the events.
        If None, a new ActionManager will be created and discarded after use.

    Returns
    -------
    dict[str, asyncio.Event]
        A mapping of event names to their corresponding asyncio.Event objects.
    """
    manager = ActionManager() if not manager else manager
    for name in names:
        manager.manage_event(name, "create")
    return manager.events
