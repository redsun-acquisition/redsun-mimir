# mypy: disable-error-code="union-attr"
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, get_args

from magicgui import widgets as mgw
from qtpy import QtWidgets

from redsun_mimir.common._plan_spec import ParamKind
from redsun_mimir.utils import ismodel, ismodelsequence, issequence

from ._treeview import DescriptorTreeView

if TYPE_CHECKING:
    from redsun_mimir.common import ParamDescription

__all__ = [
    "InfoDialog",
    "DescriptorTreeView",
    "collect_arguments",
    "create_param_widget",
]

app_name = "redsun-mimir"


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
        is_ann_model = ismodel(param.annotation)
        is_ann_model_seq = (
            ismodelsequence(param.annotation)
            or param.kind == ParamKind.VAR_POSITIONAL
            and is_ann_model
        )
        allow_multiple = is_ann_model_seq
        if is_ann_model or is_ann_model_seq:
            w = mgw.Select(
                name=param.name,
                choices=param.choices,
                allow_multiple=allow_multiple,
                annotation=param.annotation,
                value=param.default if param.has_default else param.choices[0],
            )

            # the inner native widget is a QListWidget, we can manipulate it
            # to have a better user experience and make the selection widget
            # resize it properly to the content and scrollable if too many items
            # are present
            inner_w: QtWidgets.QListWidget = w.native

            # adjust width size based on number of items;
            # the +5 is to make it a little less tight
            inner_w.setFixedWidth(
                inner_w.sizeHintForColumn(0) + inner_w.frameWidth() * 2 + 5
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
        options: dict[str, Any] = {}
        if issubclass(param.annotation, Path):
            # default to dialog mode
            options.update({"mode": "d"})
        w = mgw.create_widget(
            annotation=param.annotation,
            name=param.name,
            param_kind=param.kind.name,
            value=param.default if param.has_default else None,
            options=options,
        )
        if isinstance(w, mgw.FileEdit):
            # set a more user-friendly starting directory
            filepath = Path.home() / app_name / "storage"
            filepath.mkdir(parents=True, exist_ok=True)
            w.filter = "*.zarr"
            w.value = filepath
            w.line_edit.enabled = False

    except (TypeError, ValueError):
        # If magicgui doesn't know this annotation, fall back to a LineEdit.
        # TODO: improve this with more sophisticated handling?
        w = mgw.LineEdit(name=name)

    return w


class InfoDialog(QtWidgets.QDialog):
    """Dialog to provide information to the user.

    Parameters
    ----------
    title : ``str``
        The title of the dialog window, by default "Information"
    text : ``str``, optional
        The text to display in the text edit area.
        If ``None``, a placeholder text will be displayed.
    parent : ``QtWidgets.QWidget``, optional
        The parent widget, by default None

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
        text : ``str``, optional
            The text to display in the text edit area.
            If ``None``, a placeholder text will be displayed.
        parent : ``QtWidgets.QWidget``, optional
            The parent widget, by default None.

        Returns
        -------
        ``int``
            Dialog result code (``QDialog.Accepted``)

        """
        dialog = cls(title, text, parent)
        return dialog.exec()
