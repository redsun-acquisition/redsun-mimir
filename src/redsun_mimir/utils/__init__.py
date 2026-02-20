from collections.abc import Mapping, Sequence
from typing import Any, TypeVar, get_args, get_origin

from sunflare.device import PDevice
from typing_extensions import TypeIs

from redsun_mimir.utils.descriptors import (
    make_descriptor,
    make_key,
    make_reading,
    parse_key,
)

__all__ = [
    "filter_models",
    "get_choice_list",
    "issequence",
    "make_key",
    "parse_key",
    "make_descriptor",
    "make_reading",
    "find_signal",
]

P = TypeVar("P", bound=PDevice)


def filter_models(
    models: Mapping[str, PDevice],
    proto: type[P],
    choices: Sequence[str] | None = None,
) -> dict[str, P]:
    """Filter models by a specific protocol type and return a dictionary of names to instances.

    Parameters
    ----------
    models : ``Mapping[str, PDevice]``
        Mapping of model names to model instances.
    proto : ``type[P]``
        The protocol type to filter for.
    choices : ``Sequence[str]``, optional
        If provided, return only models associated with names in this sequence.
        Default is ``None`` (all ``proto`` models are returned).

    Returns
    -------
    ``dict[str, P]``
        Dictionary mapping model names to model instances that implement the given protocol.
    """
    if choices is not None:
        return {
            name: model
            for name, model in models.items()
            if isinstance(model, proto) and name in choices
        }
    return {name: model for name, model in models.items() if isinstance(model, proto)}


def get_choice_list(
    models: Mapping[str, PDevice], proto: type[P], choices: Sequence[str]
) -> list[P]:
    """Get a list of model names that implement a specific protocol.

    Parameters
    ----------
    models : ``Mapping[str, PDevice]``
        Mapping of model names to model instances.
    proto : ``type[P]``
        The protocol type to filter for.
    choices : ``Sequence[str]``
        Sequence of model names to consider.

    Returns
    -------
    ``list[P]``
        List of model names that implement the given protocol.
    """
    return [
        model
        for name, model in models.items()
        if isinstance(model, proto) and name in choices
    ]


def issequence(ann: Any) -> TypeIs[Sequence[Any]]:
    """Return True if annotation looks like a Sequence[...] generic."""
    origin = get_origin(ann)
    if origin is None:
        return False
    return isinstance(origin, Sequence)


def ismodelsequence(ann: Any) -> TypeIs[Sequence[PDevice]]:
    """Return True if annotation looks like a Sequence[...] of PDevice generic."""
    origin = get_origin(ann)
    if origin is None:
        return False
    args = get_args(ann)
    if len(args) != 1:
        return False
    return issubclass(origin, Sequence) and isinstance(args[0], PDevice)


def ismodel(ann: Any) -> TypeIs[PDevice]:
    """Return True if annotation looks like a PDevice generic."""
    return isinstance(ann, PDevice)


def find_signal(container: "Any", signal_name: str) -> "Any | None":
    """Find a signal in the virtual container by name, regardless of owner.

    Searches all registered signal caches for ``signal_name``,
    returning the first match. This avoids coupling to the owner's
    instance name, which is set at runtime by the application container.

    Parameters
    ----------
    container :
        The virtual container holding registered signals.
    signal_name :
        The signal name to look for (e.g. ``"sigMotorMove"``).

    Returns
    -------
    Any | None
        The signal instance, or ``None`` if not found.
    """
    for cache in container.signals.values():
        if signal_name in cache:
            return cache[signal_name]
    return None
