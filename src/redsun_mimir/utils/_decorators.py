from typing import Any, Callable, Concatenate, ParamSpec, TypeVar, overload

P = ParamSpec("P")
R = TypeVar("R")


@overload
def togglable(func: Callable[P, R]) -> Callable[P, R]: ...
@overload
def togglable(
    func: Callable[Concatenate[Any, P], R],
) -> Callable[Concatenate[Any, P], R]: ...
def togglable(
    func: Callable[P, R] | Callable[Concatenate[Any, P], R],
) -> Callable[P, R] | Callable[Concatenate[Any, P], R]:
    """Mark a function or method as togglable.

    "Togglable" means that the plan expects some mechanism
    to divert the flow of execution depending on some internal state
    which can be "toggled" by external means.

    For example: a live acquisition plan will be toggled on
    when the function is called; then when the user clicks a button,
    an internal threading.Event is cleared, which will cause
    the plan to naturally stop.
    """
    # the very long type annotation seems to be the way to
    # "eat" default arguments such as "self" or "cls"
    # for bound methods; not sure if this has any actual effect, because
    # in the issue below, they refer to defining two separate decorators
    # while this is just one, simply overloaded... will have to test it out
    # https://github.com/python/mypy/issues/13222#issuecomment-1193073470
    setattr(func, "__togglable__", True)
    return func
