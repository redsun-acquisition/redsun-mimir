"""Parameter widget factory: maps a ``ParamDescription`` to a magicgui widget.

This module is intentionally separate from ``utils.qt.__init__`` so that
``_plan_widget.py`` can import ``create_param_widget`` without creating a
circular import through the package ``__init__``.

Design
------
``create_param_widget`` delegates widget selection to a **factory registry**
— ``_WIDGET_FACTORY_MAP`` — which is an ordered list of
``(predicate, factory)`` pairs.  The first predicate that returns ``True``
for a given ``ParamDescription`` determines which factory is called.

To add support for a new annotation shape: define a predicate and a factory,
then insert a ``(predicate, factory)`` tuple at the right position in
``_WIDGET_FACTORY_MAP``.  Nothing else needs to change.

Unresolvable annotations
------------------------
``create_plan_spec`` pre-validates that every required parameter can be
mapped to a widget.  Plans with unresolvable required parameters raise
``UnresolvableAnnotationError`` and are skipped by the presenter.
``create_param_widget`` therefore raises ``RuntimeError`` (not a silent
fallback) if all factories fail, to surface bugs clearly.
"""

# mypy: disable-error-code="union-attr"
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeAlias, get_args

from magicgui import widgets as mgw
from qtpy import QtCore
from qtpy import QtWidgets as QtW

from redsun_mimir.common import ParamDescription
from redsun_mimir.common._plan_spec import ParamKind
from redsun_mimir.utils import isdevice, isdevicesequence, issequence

_app_name = "redsun-mimir"


# ---------------------------------------------------------------------------
# Compact multi-select widget
# ---------------------------------------------------------------------------


class _CompactListWidget(QtW.QListWidget):
    """A ``QListWidget`` whose ``sizeHint`` fits its content exactly.

    The default ``QListWidget.sizeHint`` returns a fixed 256×192 regardless
    of item count.  This subclass computes the minimum bounding size from the
    actual row heights and column width, so the widget shrinks to fit one item
    or expands naturally for many items.
    """

    _PADDING: int = 6  # extra px added to total height (top + bottom breathing room)

    def sizeHint(self) -> QtCore.QSize:
        """Return a size that fits all current items."""
        width = self.sizeHintForColumn(0) + self.frameWidth() * 2 + 20
        height = (
            sum(self.sizeHintForRow(i) for i in range(self.count()))
            + self.frameWidth() * 2
            + self._PADDING
        )
        return QtCore.QSize(max(width, 60), max(height, 20))

    def minimumSizeHint(self) -> QtCore.QSize:
        """Minimum size equals the full content size (no clipping)."""
        return self.sizeHint()


class CompactSelect(mgw.Select):
    """A ``Select`` widget that shrinks to fit its items.

    Replaces the inner ``QListWidget`` with a ``_CompactListWidget`` so the
    widget height reflects the actual number of choices rather than using
    Qt's fixed 192 px default.

    All parameters are forwarded unchanged to ``magicgui.widgets.Select``.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        inner: QtW.QListWidget = self.native
        inner.__class__ = _CompactListWidget
        inner.updateGeometry()


def _is_hidden_or_action(p: ParamDescription) -> bool:
    """Return true for parameters that should not get a normal input widget."""
    return p.actions is not None or p.hidden


def _is_multiselect_device(p: ParamDescription) -> bool:
    """Return true for Sequence[PDevice] or variadic *args: PDevice parameters."""
    if p.choices is None:
        return False
    is_ann_model_seq = isdevicesequence(p.annotation)
    is_var_model = p.kind is ParamKind.VAR_POSITIONAL and isdevice(p.annotation)
    return is_ann_model_seq or is_var_model


def _is_singleselect_device(p: ParamDescription) -> bool:
    """Return true for single PDevice parameters with a choices list."""
    return p.choices is not None and isdevice(p.annotation)


def _is_literal_choices(p: ParamDescription) -> bool:
    """Return true for parameters whose choices come from a Literal annotation."""
    return (
        p.choices is not None
        and not isdevice(p.annotation)
        and not isdevicesequence(p.annotation)
    )


def _is_non_device_sequence(p: ParamDescription) -> bool:
    """Return true for Sequence[T] parameters where T is not a PDevice type."""
    return (
        issequence(p.annotation)
        and not isdevicesequence(p.annotation)
        and not isinstance(p.annotation, (str, bytes))
    )


def _is_path(p: ParamDescription) -> bool:
    """Return true if the annotation is Path or a subclass."""
    try:
        return isinstance(p.annotation, type) and issubclass(p.annotation, Path)
    except TypeError:
        return False


def _always(p: ParamDescription) -> bool:
    """Catch-all predicate — always matches."""
    return True


def _make_dummy(p: ParamDescription) -> mgw.Widget:
    """Return a read-only LineEdit placeholder for hidden/action params."""
    return mgw.LineEdit(name=p.name)


def _make_multiselect(p: ParamDescription) -> mgw.Widget:
    """``CompactSelect`` widget allowing multiple device selections.

    Uses ``CompactSelect`` rather than ``mgw.Select`` so the widget height
    reflects the actual number of choices instead of the fixed 192 px default.
    """
    assert p.choices is not None
    return CompactSelect(
        name=p.name,
        choices=p.choices,
        allow_multiple=True,
        annotation=p.annotation,
        value=p.default if p.has_default else p.choices[0],
    )


def _make_singleselect_device(p: ParamDescription) -> mgw.Widget:
    """ComboBox widget for single PDevice selection."""
    assert p.choices is not None
    return mgw.ComboBox(
        name=p.name,
        choices=p.choices,
        value=p.default if p.has_default else p.choices[0],
    )


def _make_literal_combobox(p: ParamDescription) -> mgw.Widget:
    """ComboBox widget for Literal[...] choices."""
    assert p.choices is not None
    return mgw.ComboBox(
        name=p.name,
        choices=p.choices,
        value=p.default if p.has_default else p.choices[0],
    )


def _make_list_edit(p: ParamDescription) -> mgw.Widget:
    """ListEdit widget for non-device Sequence[T] parameters."""
    actual_annotation: type[Any] = Any
    args: tuple[type[Any], ...] = get_args(p.annotation)
    arg = args[0] if args else None
    if arg is not None:
        actual_annotation = list[arg]  # type: ignore[valid-type]
    else:
        actual_annotation = list
    return mgw.ListEdit(
        label=p.name,
        annotation=actual_annotation,
        layout="vertical",
    )


def _make_file_edit(p: ParamDescription) -> mgw.Widget:
    """FileEdit widget for Path parameters, pre-configured for Zarr stores."""
    w = mgw.create_widget(
        annotation=p.annotation,
        name=p.name,
        param_kind=p.kind.name,
        value=p.default if p.has_default else None,
        options={"mode": "d"},
    )
    if isinstance(w, mgw.FileEdit):
        filepath = Path.home() / _app_name / "storage"
        filepath.mkdir(parents=True, exist_ok=True)
        w.filter = "*.zarr"
        w.value = filepath
        w.line_edit.enabled = False
    return w


def _make_generic(p: ParamDescription) -> mgw.Widget:
    """Delegate to magicgui.create_widget for all other annotation types.

    Raises TypeError or ValueError if magicgui does not support the annotation.
    """
    options: dict[str, Any] = {}
    return mgw.create_widget(
        annotation=p.annotation,
        name=p.name,
        param_kind=p.kind.name,
        value=p.default if p.has_default else None,
        options=options,
    )


_WidgetPredicate: TypeAlias = Callable[[ParamDescription], bool]
_WidgetFactory: TypeAlias = Callable[[ParamDescription], mgw.Widget]

_WIDGET_FACTORY_MAP: list[tuple[_WidgetPredicate, _WidgetFactory]] = [
    (_is_hidden_or_action, _make_dummy),
    (_is_multiselect_device, _make_multiselect),
    (_is_singleselect_device, _make_singleselect_device),
    (_is_literal_choices, _make_literal_combobox),
    (_is_non_device_sequence, _make_list_edit),
    (_is_path, _make_file_edit),
    (_always, _make_generic),
]


def _try_factory_entry(
    predicate: _WidgetPredicate,
    factory: _WidgetFactory,
    param: ParamDescription,
) -> mgw.Widget | None:
    """Attempt one (predicate, factory) entry; return None on any exception."""
    try:
        if predicate(param):
            return factory(param)
        return None
    except Exception:
        return None


def create_param_widget(param: ParamDescription) -> mgw.Widget:
    """Create a magicgui widget for *param* via the factory registry.

    Parameters
    ----------
    param : ParamDescription
        The parameter specification.

    Returns
    -------
    mgw.Widget
        The created widget.

    Raises
    ------
    RuntimeError
        If every entry in ``_WIDGET_FACTORY_MAP`` fails.
    """
    for predicate, factory in _WIDGET_FACTORY_MAP:
        widget = _try_factory_entry(predicate, factory, param)
        if widget is not None:
            return widget
    raise RuntimeError(
        f"No widget factory matched parameter {param.name!r} "
        f"(annotation: {param.annotation!r}). "
        f"This is a bug — create_plan_spec should have caught this."
    )
