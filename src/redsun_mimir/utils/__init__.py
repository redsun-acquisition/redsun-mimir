from collections.abc import Mapping, Sequence
from typing import Any, TypeVar, get_args, get_origin

from sunflare.model import PModel
from typing_extensions import TypeIs

__all__ = ["filter_models", "get_choice_list", "issequence"]

P = TypeVar("P", bound=PModel)


def filter_models(
    models: Mapping[str, PModel],
    proto: type[P],
    choices: Sequence[str] | None = None,
) -> dict[str, P]:
    """Filter models by a specific protocol type and return a dictionary of names to instances.

    Parameters
    ----------
    models : ``Mapping[str, PModel]``
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
    models: Mapping[str, PModel], proto: type[P], choices: Sequence[str]
) -> list[P]:
    """Get a list of model names that implement a specific protocol.

    Parameters
    ----------
    models : ``Mapping[str, PModel]``
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


def ismodelsequence(ann: Any) -> TypeIs[Sequence[PModel]]:
    """Return True if annotation looks like a Sequence[...] of PModel generic."""
    origin = get_origin(ann)
    if origin is None:
        return False
    args = get_args(ann)
    if len(args) != 1:
        return False
    return issubclass(origin, Sequence) and isinstance(args[0], PModel)


def ismodel(ann: Any) -> TypeIs[PModel]:
    """Return True if annotation looks like a PModel generic."""
    return isinstance(ann, PModel)
