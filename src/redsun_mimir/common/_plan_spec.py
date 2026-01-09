from __future__ import annotations

import collections.abc as cabc
import inspect
from dataclasses import dataclass
from enum import IntEnum
from inspect import Parameter, _empty, signature
from typing import (
    Annotated,
    Any,
    Mapping,
    Sequence,
    get_args,
    get_origin,
    get_type_hints,
)

from sunflare.model import PModel

from redsun_mimir.actions import ActionedPlan, ActionList
from redsun_mimir.utils import get_choice_list, issequence


class ParamKind(IntEnum):
    """
    Public enum describing the "kind" of a parameter.

    Mirrors inspect._ParameterKind, but is a public IntEnum we can use
    in our own type hints and match/case statements.
    """

    POSITIONAL_ONLY = 0
    POSITIONAL_OR_KEYWORD = 1
    VAR_POSITIONAL = 2
    KEYWORD_ONLY = 3
    VAR_KEYWORD = 4


# Mapping from inspect.Parameter.kind to our ParamKind
_PARAM_KIND_MAP: dict[Any, ParamKind] = {
    Parameter.POSITIONAL_ONLY: ParamKind.POSITIONAL_ONLY,
    Parameter.POSITIONAL_OR_KEYWORD: ParamKind.POSITIONAL_OR_KEYWORD,
    Parameter.VAR_POSITIONAL: ParamKind.VAR_POSITIONAL,
    Parameter.KEYWORD_ONLY: ParamKind.KEYWORD_ONLY,
    Parameter.VAR_KEYWORD: ParamKind.VAR_KEYWORD,
}


@dataclass
class ParamDescription:
    """Description of a single plan parameter.

    Parameters
    ----------
    name : str
        Name of the parameter.
    kind : ParamKind
        Kind of the parameter (from `inspect.Parameter`).
    annotation : Any
        Type annotation of the parameter.
    default : Any
        Default value of the parameter.
    choices : list[str] | None
        Names of possible choices for this parameter (for PModel types).
    multiselect : bool
        If True, this parameter allows multiple selections (for PModel types).
    hidden : bool
        If True, this parameter should not be exposed as a normal input widget.
    actions : ActionList | None
        If this parameter is annotated as `ActionList`, this holds the associated action object.
    model_proto : type[PModel] | None
        If this parameter is associated with a PModel type,
        this holds the actual type.
    """

    name: str
    kind: ParamKind
    annotation: Any
    default: Any
    choices: list[str] | None = None
    multiselect: bool = False
    hidden: bool = False
    actions: ActionList | None = None
    model_proto: type[PModel] | None = None

    @property
    def has_default(self) -> bool:
        return self.default is not _empty


@dataclass(eq=False)
class PlanSpec:
    """Description of a plan's signature & type hints.

    Parameters
    ----------
    name: str
        Plan name.
    docs : str
        Plan docstring.
    parameters: list[ParamDescription]
        List of parameter specifications.
    togglable : bool
        Whether the plan is togglable,
        for example an infinite loop that the run engine can stop.
    """

    name: str
    docs: str
    parameters: list[ParamDescription]
    togglable: bool = False
    pausable: bool = False


def collect_arguments(
    spec: PlanSpec,
    values: cabc.Mapping[str, Any],
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Collect arguments for calling a function based on a PlanSpec.

    Build (args, kwargs) for calling the function, based on ParamDescription.kind
    and a mapping param_name -> value.

    Parameters
    ----------
    spec : PlanSpec
        The plan specification.
    values : Mapping[str, Any]
        Mapping of parameter names to values.

    Returns
    -------
    tuple[tuple[Any, ...], dict[str, Any]]
        The collected positional and keyword arguments.

    Notes
    -----
    - POSITIONAL_ONLY and POSITIONAL_OR_KEYWORD parameters go into `args`
      in declaration order.

    - KEYWORD_ONLY parameters go into `kwargs`.

    - *args are expanded into positional `args`.

    - **kwargs are expanded into keyword `kwargs`.
    """
    args: list[Any] = []
    kwargs: dict[str, Any] = {}

    for p in spec.parameters:
        if p.name not in values:
            continue
        value = values[p.name]

        match p.kind:
            case ParamKind.VAR_POSITIONAL:
                if isinstance(value, cabc.Sequence) and not isinstance(
                    value, (str, bytes)
                ):
                    args.extend(value)
                else:
                    args.append(value)
            case ParamKind.VAR_KEYWORD:
                if isinstance(value, cabc.Mapping):
                    kwargs.update(value)
                else:
                    raise TypeError(
                        f"Value for **{p.name} must be a Mapping, got {type(value)!r}"
                    )
            case ParamKind.POSITIONAL_ONLY | ParamKind.POSITIONAL_OR_KEYWORD:
                args.append(value)
            case ParamKind.KEYWORD_ONLY:
                kwargs[p.name] = value

    return tuple(args), kwargs


def resolve_arguments(
    spec: PlanSpec,
    param_values: Mapping[str, Any],
    models: Mapping[str, PModel],
) -> dict[str, Any]:
    """Resolve plan arguments from UI parameter values.

    Parameters
    ----------
    spec : ``PlanSpec``
        The plan specification containing parameter metadata.
    param_values : ``Mapping[str, Any]``
        The parameter values from the UI.
    models : ``Mapping[str, PModel]``
        The available models in the application.

    Returns
    -------
    dict[str, Any]
        The resolved arguments ready to pass to the plan function.
    """
    # start with values coming from the view
    values: dict[str, Any] = dict(param_values)

    # For ActionList-typed parameters that have metadata but no GUI input,
    # inject the ActionList instance so the function can always be called.
    for p in spec.parameters:
        if (
            isinstance(p.annotation, ActionList)
            and p.actions is not None
            and p.name not in values
        ):
            values[p.name] = p.actions

    resolved: dict[str, Any] = {}

    # For ActionList-typed parameters that have metadata but no GUI input,
    # inject the ActionList instance so the function can always be called.
    for p in spec.parameters:
        if p.name not in values:
            continue
        val = values[p.name]
        model_list: list[PModel] = []

        # Model-backed parameter: indicated by presence of choices
        if p.choices is not None:
            # Coerce widget value into a list of string labels
            if isinstance(val, str):
                labels = [val]
            elif isinstance(val, Sequence) and not isinstance(val, (str, bytes)):
                labels = [str(v) for v in val]
            else:
                labels = [str(val)]
            proto: type[PModel] | None = p.model_proto
            if proto:
                model_list = get_choice_list(models, proto, labels)

            if p.kind.name == "VAR_POSITIONAL" or issequence(p.annotation):
                # Sequence[...] or *detectors → pass the list as-is
                resolved[p.name] = model_list
            else:
                # Single model parameter → first match or None
                resolved[p.name] = model_list[0] if model_list else None
        else:
            # Non-model parameter (or no registry): pass through
            resolved[p.name] = val

    return resolved


def iterate_signature(sig: inspect.Signature) -> cabc.Iterator[tuple[str, Parameter]]:
    """Iterate over a function signature's parameters, skipping 'self'/'cls'.

    Yields
    ------
    Iterator[tuple[str, Parameter]]
        Tuples of (parameter name, Parameter object).
    """
    items = list(sig.parameters.items())

    if items:
        first_name, first_param = items[0]

        # drop only if it's actually the implicit instance/class parameter:
        if first_name in {"self", "cls"} and first_param.kind in (
            Parameter.POSITIONAL_ONLY,
            Parameter.POSITIONAL_OR_KEYWORD,
        ):
            items = items[1:]  # skip it

    for name, param in items:
        yield name, param


def create_plan_spec(
    plan: cabc.Callable[..., cabc.Generator[Any, Any, Any]],
    models: cabc.Mapping[str, PModel],
) -> PlanSpec:
    """
    Inspect `plan` and return a PlanSpec with one ParamDescription per parameter.

    Parameters
    ----------
    plan : Callable[..., Any]
        The plan to inspect.
    models : Mapping[str, PModel]
        Registry of models for computing choices
        of parameters annotated with a subclass of `PModel`.

    Returns
    -------
    PlanSpec
        The specification of the plan's signature and parameters.

    Raises
    ------
    TypeError
        If `plan` is not a generator function,
        or if the return type is not a `MsgGenerator`.

    """
    # in case plan is a method, get the underlying function object
    func_obj: cabc.Callable[..., cabc.Generator[Any, Any, Any]] = getattr(
        plan, "__func__", plan
    )

    if not inspect.isgeneratorfunction(func_obj):
        raise TypeError(f"Plan {func_obj.__name__} must be a generator function.")

    sig = signature(func_obj)

    type_hints = get_type_hints(func_obj, include_extras=True)
    return_type = type_hints.get("return", None)

    if return_type is None:
        raise TypeError(f"Plan {plan.__name__} must have a return type annotation.")

    origin = get_origin(return_type)
    isgen = origin is not None and (
        issubclass(origin, cabc.Generator) or origin is cabc.Generator
    )

    if not isgen:
        raise TypeError(f"Plan {plan.__name__} must have a MsgGenerator return type.")

    togglable = False

    if isinstance(func_obj, ActionedPlan):
        togglable = func_obj.__togglable__

    params: list[ParamDescription] = []

    for name, param in iterate_signature(sig):
        raw_ann: type[Any] = type_hints.get(name, param.annotation)
        if raw_ann is _empty:
            raw_ann = Any

        actions_meta: ActionList | None = None

        # peel Annotated[..., ActionList(...)] if present
        if get_origin(raw_ann) is Annotated:
            args = get_args(raw_ann)
            if args:
                base_ann = args[0]
                extras = args[1:]
            else:
                base_ann = Any
                extras = ()
            # TODO: for now, discard multiple extras;
            # we might add more metadata types later
            # or throw if there are unknown extras
            if len(extras) > 1:
                base_ann = Any
                extras = ()
            elif isinstance(extras[0], ActionList):
                actions_meta = extras[0]
                if param.default is not _empty and isinstance(
                    param.default, cabc.Sequence
                ):
                    # override the contents of ActionList with default value
                    actions_meta.names = list(param.default)
            ann = base_ann
        else:
            ann = raw_ann

        # If we have ActionList metadata, enforce the underlying type
        # to be Sequence[str]
        elem_ann: Any
        if actions_meta:
            _validate_action_names(name, actions_meta.names)
            if not issequence(ann):
                raise TypeError(
                    f"Parameter {name!r} uses ActionList metadata but is not "
                    f"annotated as a Sequence[...] type; got {ann!r}"
                )
            elem_args = get_args(ann)
            elem_ann = elem_args[0] if elem_args else Any
            if elem_ann is not str:
                raise TypeError(
                    f"Parameter {name!r} uses ActionList metadata but its element "
                    f"type is not str; got {elem_ann!r}"
                )

        # Now figure out if this is a sequence for other purposes
        if issequence(ann):
            elem_args = get_args(ann)
            elem_ann = elem_args[0] if elem_args else Any
        else:
            elem_ann = ann

        # Compute choices from model_registry using isinstance on actual objects
        choices: list[str] | None = None
        model_proto: type[PModel] | None = None

        matching: list[str] = []
        for key, obj in models.items():
            try:
                if isinstance(obj, elem_ann):
                    matching.append(key)
            except TypeError:
                # elem_ann might not be suitable as second arg to isinstance
                continue
        if matching:
            choices = matching
            # If elem_ann is a proper subclass of PModel, keep proto
            if isinstance(elem_ann, type) and isinstance(elem_ann, PModel):
                model_proto = elem_ann  # type: ignore[assignment]

        # Map inspect.Parameter.kind to our ParamKind
        pkind = _PARAM_KIND_MAP.get(param.kind)
        if pkind is None:
            raise RuntimeError(f"Unexpected parameter kind: {param.kind!r}")

        params.append(
            ParamDescription(
                name=name,
                kind=pkind,
                annotation=ann,
                default=param.default,
                choices=choices,
                actions=actions_meta,
                model_proto=model_proto,
            )
        )

    ret_ann: Any = type_hints.get("return", sig.return_annotation)
    if ret_ann is _empty:
        ret_ann = Any

    togglable = bool(getattr(func_obj, "__togglable__", False))
    pausable = bool(getattr(func_obj, "__pausable__", False))

    return PlanSpec(
        name=func_obj.__name__,
        docs=inspect.getdoc(func_obj) or "No documentation available.",
        parameters=params,
        togglable=togglable,
        pausable=pausable,
    )


def _validate_action_names(param_name: str, names: cabc.Sequence[str]) -> None:
    if not isinstance(names, cabc.Sequence) or isinstance(names, (str, bytes)):
        raise TypeError(
            f"ActionList for parameter {param_name!r} must be a non-string sequence of str; "
            f"got {type(names)!r}"
        )
    if not all(isinstance(x, str) for x in names):
        raise TypeError(
            f"All entries in ActionList for parameter {param_name!r} must be str; "
            f"got {names!r}"
        )
