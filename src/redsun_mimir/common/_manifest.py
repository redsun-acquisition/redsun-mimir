from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Callable,
    Generator,
    Generic,
    Mapping,
    Sequence,
    TypeVar,
    get_args,
    get_origin,
    get_type_hints,
)

from sunflare.model import ModelProtocol

if TYPE_CHECKING:
    from bluesky.utils import Msg

T = TypeVar("T")


@dataclass(frozen=True)
class Meta(Generic[T]):
    """Metadata for a plan parameter.

    Generic dataclass that can provide
    additional metadata for a plan parameter.
    The generic type `T` specifies
    the type of the parameter at initialization.

    Parameters
    ----------
    min : T, optional
        Minimum value for a parameter.
    max : T, optional
        Maximum value for a parameter.
    choices : list[str], optional
        List of possible choices for a parameter value.
        Useful to restrict, for example, the devics
        that can be selected by a widget.
    exclude : bool, optional
        If True, the parameter will not be
        generated in the UI.
        Defaults to False.
    """

    min: T | None = None
    max: T | None = None
    choices: list[str] | None = None
    exclude: bool = False


@dataclass(frozen=True)
class ParameterInfo:
    """Information about a single parameter in a plan signature.

    Parameters
    ----------
    annotation : type[Any]
        The type annotation of the parameter.
    kind : inspect._ParameterKind
        The kind of the parameter (e.g., positional, keyword).
    default : Any
        The default value of the parameter, if any.
    origin : type[Any], optional
        The origin type of the annotation, if applicable.
    meta : Meta[Any], optional
        Metadata extracted from typing.Annotated with Meta dataclass.
    choices : list[str], optional
        Available choices for the parameter (from Meta or protocol types).
    """

    annotation: type[Any]
    kind: inspect._ParameterKind
    default: Any | None = None
    origin: type[Any] | None = None
    meta: Meta[Any] | None = None
    choices: list[str] | None = None

    @classmethod
    def from_parameter(
        cls,
        param: inspect.Parameter,
        resolved_type: type[Any],
        models: Mapping[str, ModelProtocol] | None = None,
    ) -> "ParameterInfo":
        """Create a ParameterInfo from an inspect.Parameter and resolved type.

        Parameters
        ----------
        param : inspect.Parameter
            The parameter to extract information from.
        resolved_type : type[Any]
            The resolved type annotation.
        models : Mapping[str, ModelProtocol], optional
            Mapping of model names to model instances for extracting protocol choices.

        Returns
        -------
        ParameterInfo
            A new ParameterInfo instance with the extracted information.
        """
        origin = get_origin(resolved_type)

        # Extract Meta metadata from Annotated types
        meta = _extract_metadata_from_annotated(resolved_type)

        # Extract choices from Meta or protocol types
        choices = None
        if meta and meta.choices:
            choices = meta.choices
        elif models and _is_protocol_type(resolved_type):
            protocol_type = _extract_protocol_type(resolved_type)
            if protocol_type:
                choices = extract_protocol_choices(protocol_type, models)

        return cls(
            annotation=resolved_type,
            kind=param.kind,
            default=param.default if param.default != inspect.Parameter.empty else None,
            origin=origin,
            meta=meta,
            choices=choices,
        )


@dataclass(frozen=True)
class PlanManifest:
    """Encapsulation of a plan's signature and metadata.

    Parameters
    ----------
    name : str
        The name of the plan function.
    display_name : str
        A user-friendly name for the plan.
    description : str
        Docstring of the plan function.
        Extracted via `inspect.getdoc`.
    parameters : dict[str, ParameterInfo]
        A dictionary mapping parameter names to their metadata.
    is_toggleable : bool, optional
        Indicates if the plan is togglable.
        Defaults to False.
    """

    name: str
    display_name: str
    description: str
    parameters: dict[str, ParameterInfo]
    is_toggleable: bool = False  # For continuous plans like live_count


def extract_protocol_choices(
    protocol_type: type[ModelProtocol], models: Mapping[str, ModelProtocol]
) -> list[str]:
    """Extract available model names for a specific protocol type.

    Parameters
    ----------
    protocol_type : type[ModelProtocol]
        The protocol type to filter for.
    models : Mapping[str, ModelProtocol]
        Mapping of model names to model instances.

    Returns
    -------
    list[str]
        List of model names that implement the given protocol.
    """
    return [name for name, model in models.items() if isinstance(model, protocol_type)]


def _extract_metadata_from_annotated(annotation: Any) -> Meta[Any] | None:
    """Extract Meta metadata from typing.Annotated annotations.

    Parameters
    ----------
    annotation : Any
        The type annotation to inspect.

    Returns
    -------
    Meta[Any] | None
        The Meta instance if found, None otherwise.
    """
    origin = get_origin(annotation)
    if origin is Annotated:
        args = get_args(annotation)
        if len(args) > 1:
            # Check all metadata args for Meta instances
            for metadata in args[1:]:
                if isinstance(metadata, Meta):
                    return metadata
    return None


def _get_base_type(annotation: Any) -> Any:
    """Get the base type from an annotation, handling Annotated types.

    Parameters
    ----------
    annotation : Any
        The type annotation to inspect.

    Returns
    -------
    Any
        The base type without Annotated wrapper.
    """
    origin = get_origin(annotation)
    if origin is Annotated:
        args = get_args(annotation)
        if args:
            return args[0]  # First arg is the actual type
    return annotation


def _is_protocol_type(annotation: Any) -> bool:
    """Check if an annotation represents a ModelProtocol type.

    Parameters
    ----------
    annotation : Any
        The type annotation to check.

    Returns
    -------
    bool
        True if the annotation is a ModelProtocol type or contains one.
    """
    base_type = _get_base_type(annotation)

    # Direct protocol check
    if (
        isinstance(base_type, type)
        and hasattr(base_type, "__mro__")
        and ModelProtocol in base_type.__mro__
    ):
        return True

    # Check for generic types containing protocols
    origin = get_origin(base_type)
    if origin in (Sequence, list, tuple, set):
        args = get_args(base_type)
        if args and len(args) > 0:
            inner_type = args[0]
            return isinstance(inner_type, ModelProtocol)

    return False


def _extract_protocol_type(annotation: Any) -> type[ModelProtocol] | None:
    """Extract the protocol type from an annotation.

    Parameters
    ----------
    annotation : Any
        The type annotation to inspect.

    Returns
    -------
    type[ModelProtocol] | None
        The protocol type if found, None otherwise.
    """
    base_type = _get_base_type(annotation)

    # Direct protocol check
    if (
        isinstance(base_type, type)
        and hasattr(base_type, "__mro__")
        and ModelProtocol in base_type.__mro__
    ):
        return base_type

    # Check for generic types containing protocols
    origin = get_origin(base_type)
    if origin in (Sequence, list, tuple, set):
        args = get_args(base_type)
        if args and len(args) > 0:
            inner_type = args[0]
            if (
                isinstance(inner_type, type)
                and hasattr(inner_type, "__mro__")
                and ModelProtocol in inner_type.__mro__
            ):
                return inner_type

    return None


def generate_plan_manifest(
    plan_func: Callable[..., Generator[Msg, Any, Any]],
    models: Mapping[str, ModelProtocol],
) -> PlanManifest:
    """Generate a plan manifest from a function signature.

    This function inspects the signature of a plan function and automatically
    generates a PlanManifest that includes:
    - Parameter type information
    - Choices for ModelProtocol parameters from the models mapping
    - Metadata from typing.Annotated with Meta dataclass
    - Default values and constraints

    Parameters
    ----------
    plan_func : Callable[..., Generator[Msg, Any, Any]]
        The plan function to inspect. Must be a generator function
        yielding Msg objects.
    models : Mapping[str, ModelProtocol]
        Mapping of model names to model instances for extracting choices.

    Returns
    -------
    PlanManifest
        Complete manifest for generating UI for the plan.

    Examples
    --------
    >>> def my_plan(
    ...     detectors: Sequence[DetectorProtocol],
    ...     exposure: Annotated[float, Meta(min=0.1, max=10.0)],
    ... ) -> Generator[Msg, Any, Any]:
    ...     # plan implementation
    ...     pass
    >>> manifest = generate_plan_manifest(my_plan, models)
    >>> print(manifest.parameters["detectors"].choices)
    ['camera1', 'camera2']
    >>> print(manifest.parameters["exposure"].min_value)
    0.1
    """
    if not inspect.isgeneratorfunction(plan_func):
        raise TypeError(
            f"Plan function {plan_func.__name__} must be a generator function"
        )

    sig = inspect.signature(plan_func)
    type_hints = get_type_hints(plan_func, include_extras=True)

    plan_name = plan_func.__name__
    display_name = plan_name.replace("_", " ")
    plan_description = inspect.getdoc(plan_func)
    if not plan_description:
        plan_description = "No description available."

    parameters: dict[str, ParameterInfo] = {}

    for param_name, param in sig.parameters.items():
        # get resolved type from type hints, fallback to annotation
        resolved_type = type_hints.get(param_name, param.annotation)
        parameters[param_name] = ParameterInfo.from_parameter(
            param, resolved_type, models=models
        )

    return PlanManifest(
        name=plan_name,
        display_name=display_name,
        description=plan_description,
        parameters=parameters,
        is_toggleable=getattr(plan_func, "__togglable__", False),
    )
