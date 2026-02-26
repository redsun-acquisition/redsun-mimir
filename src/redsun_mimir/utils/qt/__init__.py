"""Qt widget factory for plan parameters.

Design
------
``create_param_widget`` is the public entry point.  It delegates widget
selection to a **factory registry** — ``_WIDGET_FACTORY_MAP`` — which is
an ordered list of ``(predicate, factory)`` pairs.  The first predicate
that returns ``True`` for a given ``ParamDescription`` determines which
factory function is called.

**Extending the system**: to add support for a new annotation/parameter
shape, define a predicate and a factory function, then insert a
``(predicate, factory)`` tuple at the appropriate position in
``_WIDGET_FACTORY_MAP``.  Nothing else needs to change.

Unresolvable annotations
------------------------
``create_plan_spec`` (in ``common._plan_spec``) pre-validates that every
required parameter in a plan can be mapped to a widget before the plan is
registered.  Plans with unresolvable required parameters raise
``UnresolvableAnnotationError`` at construction time and are skipped by
the presenter.  Therefore ``create_param_widget`` should never encounter
an annotation it cannot handle; if it does, a ``RuntimeError`` is raised
(not a silent fallback) to surface the bug clearly.

Widget types used
-----------------
* ``magicgui.widgets.Select``   – multi-select list (``PDevice`` sequences)
* ``magicgui.widgets.ComboBox`` – single-select dropdown (single ``PDevice``
  or ``Literal`` choices)
* ``magicgui.widgets.ListEdit`` – editable list for non-device ``Sequence[T]``
* ``magicgui.widgets.FileEdit`` – file/directory picker for ``Path``
* ``magicgui.widgets.create_widget`` – catch-all via magicgui's type map
"""

# mypy: disable-error-code="union-attr"
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeAlias, get_args

from magicgui import widgets as mgw
from qtpy import QtWidgets

from redsun_mimir.common import ParamDescription
from redsun_mimir.common._plan_spec import ParamKind
from redsun_mimir.utils import isdevice, isdevicesequence, issequence

from ._treeview import DescriptorTreeView

__all__ = [
    "InfoDialog",
    "DescriptorTreeView",
    "create_param_widget",
]

app_name = "redsun-mimir"

# ---------------------------------------------------------------------------
# Widget predicates
# ---------------------------------------------------------------------------
# Each predicate takes a ``ParamDescription`` and returns ``bool``.
# They are evaluated in the order they appear in ``_WIDGET_FACTORY_MAP``.


def _is_hidden_or_action(p: ParamDescription) -> bool:
    """Return true for parameters that should not get a normal input widget."""
    return p.actions is not None or p.hidden


def _is_multiselect_device(p: ParamDescription) -> bool:
    """Return true for ``Sequence[PDevice]`` or variadic ``*args: PDevice`` parameters."""
    if p.choices is None:
        return False
    is_ann_model_seq = isdevicesequence(p.annotation)
    is_var_model = p.kind is ParamKind.VAR_POSITIONAL and isdevice(p.annotation)
    return is_ann_model_seq or is_var_model


def _is_singleselect_device(p: ParamDescription) -> bool:
    """Return true for single ``PDevice`` parameters with a choices list."""
    return p.choices is not None and isdevice(p.annotation)


def _is_literal_choices(p: ParamDescription) -> bool:
    """Return true for parameters whose choices come from a ``Literal`` annotation."""
    return (
        p.choices is not None
        and not isdevice(p.annotation)
        and not isdevicesequence(p.annotation)
    )


def _is_non_device_sequence(p: ParamDescription) -> bool:
    """Return true for ``Sequence[T]`` parameters where ``T`` is not a ``PDevice`` type."""
    return (
        issequence(p.annotation)
        and not isdevicesequence(p.annotation)
        and not isinstance(p.annotation, (str, bytes))
    )


def _is_path(p: ParamDescription) -> bool:
    """Return true if the annotation is ``Path`` or a subclass."""
    try:
        return isinstance(p.annotation, type) and issubclass(p.annotation, Path)
    except TypeError:
        return False


def _always(p: ParamDescription) -> bool:
    """Catch-all predicate — always matches."""
    return True


def _make_dummy(p: ParamDescription) -> mgw.Widget:
    """Return a read-only ``LineEdit`` placeholder for hidden/action params."""
    return mgw.LineEdit(name=p.name)


def _make_multiselect(p: ParamDescription) -> mgw.Widget:
    """``Select`` widget allowing multiple device selections."""
    assert p.choices is not None  # predicate guarantees this
    w = mgw.Select(
        name=p.name,
        choices=p.choices,
        allow_multiple=True,
        annotation=p.annotation,
        value=p.default if p.has_default else p.choices[0],
    )
    # Resize the inner QListWidget to fit its content, with a small padding.
    inner: QtWidgets.QListWidget = w.native
    inner.setFixedWidth(inner.sizeHintForColumn(0) + inner.frameWidth() * 2 + 5)
    return w


def _make_singleselect_device(p: ParamDescription) -> mgw.Widget:
    """``ComboBox`` widget for single ``PDevice`` selection."""
    assert p.choices is not None
    return mgw.ComboBox(
        name=p.name,
        choices=p.choices,
        value=p.default if p.has_default else p.choices[0],
    )


def _make_literal_combobox(p: ParamDescription) -> mgw.Widget:
    """``ComboBox`` widget for ``Literal[...]`` choices."""
    assert p.choices is not None
    return mgw.ComboBox(
        name=p.name,
        choices=p.choices,
        value=p.default if p.has_default else p.choices[0],
    )


def _make_list_edit(p: ParamDescription) -> mgw.Widget:
    """``ListEdit`` widget for non-model ``Sequence[T]`` parameters."""
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
    """``FileEdit`` widget for ``Path`` parameters, pre-configured for Zarr stores."""
    w = mgw.create_widget(
        annotation=p.annotation,
        name=p.name,
        param_kind=p.kind.name,
        value=p.default if p.has_default else None,
        options={"mode": "d"},
    )
    if isinstance(w, mgw.FileEdit):
        filepath = Path.home() / app_name / "storage"
        filepath.mkdir(parents=True, exist_ok=True)
        w.filter = "*.zarr"
        w.value = filepath
        w.line_edit.enabled = False
    return w


def _make_generic(p: ParamDescription) -> mgw.Widget:
    """Delegate to ``magicgui.create_widget`` for all other annotation types.

    Raises ``TypeError`` or ``ValueError`` if magicgui does not support the
    annotation.  This should never be reached for required parameters because
    ``create_plan_spec`` pre-checks resolvability via
    ``_is_magicgui_resolvable`` and raises ``UnresolvableAnnotationError``
    before a plan with such a parameter is registered.
    """
    options: dict[str, Any] = {}
    return mgw.create_widget(
        annotation=p.annotation,
        name=p.name,
        param_kind=p.kind.name,
        value=p.default if p.has_default else None,
        options=options,
    )


# ---------------------------------------------------------------------------
# Widget factory registry
# ---------------------------------------------------------------------------
# Each entry is (predicate, factory).
# Predicates and factories both take a ``ParamDescription``.
# Entries are checked in order; the first match wins.
#
# To extend: insert a ``(predicate, factory)`` pair at the right priority.
# ---------------------------------------------------------------------------

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
    """Attempt one ``(predicate, factory)`` entry; return ``None`` on any exception.

    Isolating the try/except here keeps it out of the ``for`` loop body in
    ``create_param_widget``, satisfying ruff's PERF203 rule without
    suppressing it via ``noqa``.
    """
    try:
        if predicate(param):
            return factory(param)
        return None
    except Exception:
        return None


def create_param_widget(param: ParamDescription) -> mgw.Widget:
    """Create a magicgui widget for *param* via the factory registry.

    Walks ``_WIDGET_FACTORY_MAP`` in order; the first predicate that matches
    determines which factory is called.

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
        If every entry in ``_WIDGET_FACTORY_MAP`` fails.  This should not
        happen in normal usage because ``create_plan_spec`` pre-validates
        that all required parameters are resolvable before the plan is
        registered.
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


# ---------------------------------------------------------------------------
# InfoDialog
# ---------------------------------------------------------------------------


class InfoDialog(QtWidgets.QDialog):
    """Dialog to provide information to the user.

    Parameters
    ----------
    title : ``str``
        The title of the dialog window.
    text : ``str``
        The text to display in the text edit area (rendered as Markdown).
    parent : ``QtWidgets.QWidget``, optional
        The parent widget, by default ``None``.
    """

    def __init__(
        self,
        title: str,
        text: str,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.setWindowTitle(title)
        self.resize(500, 300)

        layout = QtWidgets.QVBoxLayout(self)

        self.text_edit = QtWidgets.QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setMarkdown(text)
        layout.addWidget(self.text_edit)

        self.ok_button = QtWidgets.QPushButton("OK")
        self.ok_button.setDefault(True)
        self.ok_button.clicked.connect(self.accept)

        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(self.ok_button)
        layout.addLayout(button_layout)

        self.setLayout(layout)

    @classmethod
    def show_dialog(
        cls, title: str, text: str, parent: QtWidgets.QWidget | None = None
    ) -> int:
        """Create and show the dialog in one step.

        Parameters
        ----------
        title : ``str``
            The title of the dialog window.
        text : ``str``
            The text to display in the text edit area.
        parent : ``QtWidgets.QWidget``, optional
            The parent widget, by default ``None``.

        Returns
        -------
        ``int``
            Dialog result code (``QDialog.Accepted`` or ``QDialog.Rejected``).
        """
        dialog = cls(title, text, parent)
        return dialog.exec()
