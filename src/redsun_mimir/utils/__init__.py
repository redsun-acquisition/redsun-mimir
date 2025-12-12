from collections.abc import Mapping, Sequence
from typing import Any, TypeVar, get_origin

from sunflare.model import ModelProtocol
from typing_extensions import TypeIs

__all__ = ["filter_models", "get_choice_list", "issequence"]

P = TypeVar("P", bound=ModelProtocol)


def filter_models(
    models: Mapping[str, ModelProtocol],
    proto: type[P],
    choices: Sequence[str] | None = None,
) -> dict[str, P]:
    """Filter models by a specific protocol type and return a dictionary of names to instances.

    Parameters
    ----------
    models : ``Mapping[str, ModelProtocol]``
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
    models: Mapping[str, ModelProtocol], proto: type[P], choices: Sequence[str]
) -> list[P]:
    """Get a list of model names that implement a specific protocol.

    Parameters
    ----------
    models : ``Mapping[str, ModelProtocol]``
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
    return isinstance(origin, Sequence) or issubclass(origin, Sequence)
