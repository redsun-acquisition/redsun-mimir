from __future__ import annotations

from typing import TYPE_CHECKING

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
