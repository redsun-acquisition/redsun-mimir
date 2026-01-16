from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, ParamSpec, Protocol, TypeVar, cast, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable

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
    "actioned",
]
