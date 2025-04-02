from functools import wraps
from typing import Callable, ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


def togglable(func: Callable[P, R]) -> Callable[P, R]:
    """Mark a plan as togglable.

    Parameters
    ----------
    func : ``Callable``
        The function to be decorated.

    Returns
    -------
    ``Callable``
        The decorated function with the ``__togglable__`` attribute set to True.

    Notes
    -----
    This decorator adds a boolean attribute ```__togglable__``` to the function,
    which can be used to identify plans that support toggling behavior.

    """

    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        return func(*args, **kwargs)

    setattr(wrapper, "__togglable__", True)

    return wrapper
