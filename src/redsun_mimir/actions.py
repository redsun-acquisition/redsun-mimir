from __future__ import annotations

import asyncio
from abc import abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ParamSpec, Protocol, TypeVar, cast, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable

P = ParamSpec("P")
R = TypeVar("R")
R_co = TypeVar("R_co", covariant=True)


class SRLatch:
    """An Event-like class that behaves as a set-reset latch.

    Wraps two asyncio.Event objects to allow waiting
    for either the set or reset state of the latch.
    At object creation, the latch is in the reset state.
    """

    def __init__(self) -> None:
        self._flag: bool = False
        self._set_event: asyncio.Event = asyncio.Event()
        self._reset_event: asyncio.Event = asyncio.Event()

        # reset the latch
        self._reset_event.set()

    def set(self) -> None:
        """Set the internal flag to True.

        All coroutines waiting for the flag to be set will be awakened.
        """
        if not self._flag:
            self._flag = True
            self._set_event.set()
            self._reset_event.clear()

    def reset(self) -> None:
        """Reset the internal flag to False.

        All coroutines waiting for the flag to be reset will be awakened.
        """
        if self._flag:
            self._flag = False
            self._reset_event.set()
            self._set_event.clear()

    def is_set(self) -> bool:
        """Return True if the internal flag is set, False otherwise."""
        return self._flag

    async def wait_for_set(self) -> None:
        """Wait until the internal flag is set.

        If the flag is already set, return immediately.
        Otherwise, block until another coroutine calls set().
        """
        if self._flag:
            return
        await self._set_event.wait()

    async def wait_for_reset(self) -> None:
        """Wait until the internal flag is reset.

        If the flag is already reset, return immediately.
        Otherwise, block until another coroutine calls reset().
        """
        if not self._flag:
            return
        await self._reset_event.wait()


def continous(
    togglable: bool = False,
    pausable: bool = False,
) -> Callable[[Callable[P, R_co]], ContinousPlan[P, R_co]]:
    """Mark a plan as continous.

    A "continous" plan informs the view to provide UI elements
    that allow the user to start, stop, pause, and resume the plan execution.

    Parameters
    ----------
    togglable : bool, optional
        Whether the plan is togglable (i.e. an infinite loop that the run engine can stop.)
    pausable : bool, optional
        Whether the plan is pausable (i.e. can be paused and resumed by the run engine.)

    Returns
    -------
    ``Callable[[Callable[P, R_co]], ContinousPlan[P, R_co]]``
        A decorator that marks the plan as continous.

    Example
    -------
    >>> @continous(togglable=True, pausable=True)
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

    def decorator(func: Callable[P, R_co]) -> ContinousPlan[P, R_co]:
        setattr(func, "__togglable__", togglable)
        setattr(func, "__pausable__", pausable)

        return cast("ContinousPlan[P, R_co]", func)

    return decorator


@dataclass(kw_only=True)
class Action:
    """Action container.

    Provides metadata about an action that
    can be performed on a continous plan.
    Encapsulates an `asyncio.Event` synchronization
    primitive to signal when the action has been triggered.

    Can be subclassed to add more fields as needed.

    Attributes
    ----------
    name : str
        The name of the action.
    description : str, optional
        A brief description of the action.
        Usable to populate tooltips in the UI.
        Defaults to an empty string (no description).
    togglable : bool, optional
        Whether the action is togglable.
        Allows the UI to represent the action
        as a toggle button.
        Default is False (one-shot action).
    toggle_states : tuple[str, str], optional
        The labels for the two states of the toggle action.
        Unused if `togglable` is False.
        Default is ("On", "Off").
    """

    name: str
    description: str = field(default="")
    togglable: bool = field(default=False)
    toggle_states: tuple[str, str] = field(default=("On", "Off"))
    _latch: SRLatch | None = field(init=False, default=None, repr=False)

    @property
    def event_map(self) -> dict[str, SRLatch]:
        """Returns the latch associated to this action as a single-item dict."""
        if not self._latch:
            self._latch = SRLatch()
        return {self.name: self._latch}


@runtime_checkable
class ContinousPlan(Protocol[P, R_co]):
    """
    Plan that has been marked as continous.

    "Actioned" means that the internal flow of the plan can be influenced
    by external actions, typically triggered by user interaction.

    Used both for static typing (decorator return type) and for runtime checks:

    >>> if isinstance(f, ContinousPlan):
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

    Use with `typing.Annotated` to specify action names
    for a plan or function parameter.

    Example:
        >>> from typing import Annotated as A

        >>> # specify action names via the constructor...
        >>> def my_func(
        >>>    detectors: Sequence[DetectorProtocol],
        >>>    actions: A[Sequence[str], ActionList(names=["do_this", "do_that"])]
        >>> ) -> None:
        >>>    ...

        >>> # ...or via default argument values,
        >>> # convenient in case of keyword-only arguments
        >>> def my_func(
        >>>    detectors: Sequence[DetectorProtocol],
        >>>    /,
        >>>    actions: A[Sequence[str], ActionList()] = ["do_this", "do_that"]
        >>> ) -> None:

    Parameters
    ----------
    names : list[str] | None, optional
        The list of action names.
        If None or not provided, defaults to an empty list.
    """

    names: list[str]

    def __init__(self, names: list[str] | None = None) -> None:
        self.names = names or []


__all__ = [
    "Action",
    "ContinousPlan",
    "continous",
]
