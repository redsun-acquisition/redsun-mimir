from __future__ import annotations

from typing import TYPE_CHECKING, Any, get_args

from magicgui import widgets as mgw

from redsun_mimir.common._plan_spec import ParamKind
from redsun_mimir.utils import issequence

if TYPE_CHECKING:
    from redsun_mimir.common import ParamDescription


def create_param_widget(param: ParamDescription) -> mgw.Widget:
    """
    Create a magicgui widget for a single parameter, based solely on ParamDescription.

    Parameters
    ----------
    param : ParamDescription
        The parameter specification.

    Returns
    -------
    mgw.Widget
        The created magicgui widget.

    Notes
    -----
    - If `param.events` is not None or `param.hidden` is True, this param is
    not meant to be a normal input widget (the View should not request one).

    - If `param.choices` is not None, we build a Select widget with optional
    multi-selection, using the (label, value) pairs in `param.choices`.

    - Otherwise, we use magicgui's type mapping via `annotation`.
    """
    w: mgw.Widget

    if param.actions is not None or param.hidden:
        # View should not generally request a widget for hidden/events params,
        # but if it does, just return a dummy widget.
        return mgw.LineEdit(name=param.name)

    if param.choices is not None:
        if param.kind == ParamKind.VAR_POSITIONAL or issequence(param.annotation):
            # Multi-select
            w = mgw.Select(
                name=param.name,
                choices=param.choices,
                allow_multiple=True,
                annotation=param.annotation,
                value=param.default if param.has_default else None,
            )
        else:
            w = mgw.ComboBox(
                name=param.name,
                choices=param.choices,
                value=param.default if param.has_default else param.choices[0],
            )
        return w

    # non-model sequence: Sequence[float, int, ...];
    # str and bytes are also sequences, but should not be treated as such
    # for the purpose of this use case and falls back to magicgui's default handling
    if issequence(param.annotation) and not isinstance(param.annotation, (str, bytes)):
        actual_annotation: type[Any] = Any

        # convert Sequence[T] to list[T] for magicgui
        args: tuple[type[Any]] = get_args(param.annotation)
        arg = args[0] if len(args) > 0 else None
        if arg:
            actual_annotation = list[arg]  # type: ignore[valid-type]
        else:
            actual_annotation = list

        w = mgw.ListEdit(
            label=param.name,
            annotation=actual_annotation,
            layout="vertical",
        )
        return w

    name = param.name
    # fallback to regular widget creation
    # for normal parameters
    try:
        w = mgw.create_widget(
            annotation=param.annotation,
            name=param.name,
            param_kind=param.kind.name,
            value=param.default if param.has_default else None,
        )
    except (TypeError, ValueError):
        # If magicgui doesn't know this annotation, fall back to a LineEdit.
        # TODO: improve this with more sophisticated handling?
        w = mgw.LineEdit(name=name)

    return w
