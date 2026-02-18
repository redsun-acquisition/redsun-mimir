from collections.abc import Mapping, Sequence
from typing import Any, TypeVar, get_args, get_origin

from sunflare.device import PDevice
from typing_extensions import TypeIs

from redsun_mimir.utils.descriptors import (
    make_array_descriptor,
    make_descriptor,
    make_enum_descriptor,
    make_integer_descriptor,
    make_key,
    make_number_descriptor,
    make_reading,
    make_string_descriptor,
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
    # backwards-compatible wrappers
    "make_number_descriptor",
    "make_integer_descriptor",
    "make_string_descriptor",
    "make_enum_descriptor",
    "make_array_descriptor",
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
