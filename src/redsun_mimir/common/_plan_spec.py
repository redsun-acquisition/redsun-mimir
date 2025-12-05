from __future__ import annotations

import collections.abc as cabc
import inspect
from abc import abstractmethod
from dataclasses import dataclass, field
from enum import IntEnum
from inspect import Parameter, _empty, signature
from typing import (
    TYPE_CHECKING,
    Any,
    ParamSpec,
    Protocol,
    TypeVar,
    cast,
    get_args,
    get_origin,
    get_type_hints,
    runtime_checkable,
)

from redsun_mimir.utils import issequence

if TYPE_CHECKING:
    from sunflare.model import ModelProtocol

P = ParamSpec("P")
R = TypeVar("R")
R_co = TypeVar("R_co", covariant=True)


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


@dataclass
class AnnotatedInfo:
    """Information extracted from typing.Annotated[T, *metadata]."""

    base_type: Any
    metadata: tuple[Any, ...] = field(default_factory=tuple)


@dataclass
class EventsInfo:
    """Runtime info for an events parameter."""

    names: list[str]


@runtime_checkable
class ActionedFunction(Protocol[P, R_co]):
    """
    Callable that has been marked as actioned.

    "Actioned" means that the internal flow of the function can be influenced
    by external actions, typically triggered by user interaction.

    Used both for static typing (decorator return type) and for runtime checks:

    >>> if isinstance(f, ActionedFunction):
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
    __actions__: cabc.Mapping[str, Actions]

    @abstractmethod
    def __call__(
        self, *args: P.args, **kwargs: P.kwargs
    ) -> R_co:  # pragma: no cover - protocol
        ...


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
    annotated : AnnotatedInfo | None
        If the parameter is annotated with `typing.Annotated`, this holds
        the extracted information. Otherwise, None.
    choices : list[str] | None
        Names of possible choices for this parameter (for ModelProtocol types).
    multiselect : bool
        If True, this parameter allows multiple selections (for ModelProtocol types).
    hidden : bool
        If True, this parameter should not be exposed as a normal input widget.
    events : EventsInfo | None
        If this parameter represents events, this holds the event names.
    """

    name: str
    kind: ParamKind
    annotation: Any
    default: Any
    annotated: AnnotatedInfo | None = None
    choices: list[str] | None = None
    multiselect: bool = False
    hidden: bool = False
    actions: Actions | None = None

    @property
    def has_default(self) -> bool:
        return self.default is not _empty


@dataclass
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
    """

    name: str
    docs: str
    parameters: list[ParamDescription]


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


def create_plan_spec(
    plan: cabc.Callable[..., cabc.Generator[Any, Any, Any]],
    models: cabc.Mapping[str, ModelProtocol],
) -> PlanSpec:
    """
    Inspect `plan` and return a PlanSpec with one ParamDescription per parameter.

    Parameters
    ----------
    plan : Callable[..., Any]
        The plan to inspect.
    models : Mapping[str, ModelProtocol]
        Registry of models for computing choices
        of parameters annotated with a subclass of `ModelProtocol`.

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

    if (
        sig.return_annotation is _empty
        or get_origin(sig.return_annotation) is None
        or not isinstance(get_origin(sig.return_annotation), cabc.Generator)
    ):
        raise TypeError(f"Plan {plan.__name__} must have a MsgGenerator return type.")

    type_hints = get_type_hints(plan, include_extras=True)

    func_actions_meta: cabc.Mapping[str, Actions] = {}

    if isinstance(func_obj, ActionedFunction):
        func_actions_meta = func_obj.__actions__

    params: list[ParamDescription] = []

    for name, param in sig.parameters.items():
        ann: Any = type_hints.get(name, param.annotation)
        if ann is _empty:
            ann = Any

        actions: Actions | None = None

        # If the parameter type is Actions, and we have a default Actions
        # instance, capture it for the UI.
        # Direct default: events: Actions = Actions(names=[...])
        if ann is Actions:
            default_val = param.default
            if default_val is not _empty and isinstance(default_val, Actions):
                _validate_action_names(name, default_val.names)
                actions = default_val

        # Decorator-based metadata (overrides default if present)
        if name in func_actions_meta:
            actions = func_actions_meta[name]

        # Decide which annotation we use for matching registry objects:
        # - For Sequence[T], use T
        # - Otherwise, use the annotation itself
        if issequence(ann):
            elem_args = get_args(ann)
            elem_ann: Any = elem_args[0] if elem_args else Any
        else:
            elem_ann = ann

        # Find possible choices using isinstance on actual objects
        choices: list[str] | None = None
        matching: list[str] = []
        for key, obj in models.items():
            try:
                if isinstance(obj, elem_ann):
                    matching.append(key)
            except TypeError:
                continue
        if matching:
            choices = matching

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
                actions=actions,
            )
        )

    return PlanSpec(
        name=plan.__name__,
        docs=inspect.getdoc(plan) or "No documentation available.",
        parameters=params,
    )


def _validate_action_names(param_name: str, names: cabc.Sequence[str]) -> None:
    if not isinstance(names, cabc.Sequence) or isinstance(names, (str, bytes)):
        raise TypeError(
            f"Actions for parameter {param_name!r} must be a non-string sequence of str; "
            f"got {type(names)!r}"
        )
    if not all(isinstance(x, str) for x in names):
        raise TypeError(
            f"All entries in Actions for parameter {param_name!r} must be str; "
            f"got {names!r}"
        )


def actioned(
    mapping: cabc.Mapping[str, cabc.Sequence[str]],
    togglable: bool = False,
) -> cabc.Callable[[cabc.Callable[P, R_co]], ActionedFunction[P, R_co]]:
    """Attach action names to parameters typed as `Actions`.

    Parameters
    ----------
    mapping : ``Mapping[str, Sequence[str]]``
        Mapping of parameter names to sequences of action names.ù
    togglable : bool, optional
        Whether the function is togglable (i.e. an infinite loop that the run engine can stop.)

    Returns
    -------
    ``Callable[[Callable[P, R_co]], ActionedFunction[P, R_co]]``
        A decorator that marks the function as actioned.

    Example
    -------
        @actioned({"events": ["stop", "pause"]})
        def live_count(
            detectors: Sequence[DetectorProtocol],
            /,
            events: Actions,
        ) -> MsgGenerator[None]:
            ...

    Raises
    ------
    ``TypeError``
        If any parameter in `mapping` is not annotated as `Actions`,
        or if the associated value is not a sequence of strings.

    Notes
    -----
    This does not modify the function signature; instead it stores the
    information on the underlying function object (in ``__actions__``),
    to be retrieved later by inspection.
    Keys in `mapping` must correspond to parameter names annotated as `Actions`.
    """

    def decorator(func: cabc.Callable[P, R_co]) -> ActionedFunction[P, R_co]:
        hints = get_type_hints(func, include_extras=True)
        actions_map: dict[str, Actions] = {}

        for param_name, names in mapping.items():
            ann = hints.get(param_name, None)
            if ann is not Actions:
                raise TypeError(
                    f"Parameter {param_name!r} must be annotated as Actions "
                    f"to use @actioned; got {ann!r}"
                )
            _validate_action_names(param_name, names)
            actions_map[param_name] = Actions(list(names))

        # Merge with any existing mapping (later decorators override earlier)
        existing: cabc.Mapping[str, Actions] | None = getattr(func, "__actions__", None)
        if existing:
            merged = dict(existing)
            merged.update(actions_map)
            actions_map = merged

        setattr(func, "__actions__", actions_map)
        setattr(func, "__togglable__", togglable)

        # Tell the type checker (and runtime protocol) that this callable
        # now satisfies ActionedFunction[PS, R_co].
        return cast("ActionedFunction[P, R_co]", func)

    return decorator
