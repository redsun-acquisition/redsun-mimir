# mypy: disable-error-code="union-attr"
from __future__ import annotations

from typing import TYPE_CHECKING

from magicgui import widgets as mgw
from qtpy import QtWidgets

from redsun_mimir.common._plan_spec import ParamKind
from redsun_mimir.utils import issequence

from ._treeview import DescriptorTreeView

if TYPE_CHECKING:
    from redsun_mimir.common import ParamDescription

__all__ = [
    "InfoDialog",
    "DescriptorTreeView",
    "collect_arguments",
    "create_param_widget",
]


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
                value=param.default if param.has_default else param.choices[0],
            )
            # the inner native widget is a QListWidget, we can manipulate it
            # to have a better user experience and make the selection widget
            # resize it properly to the content and scrollable if too many items
            # are present
            inner_w: QtWidgets.QListWidget = w.native
            height = 2 * inner_w.frameWidth()  # top + bottom frame

            # get number of rows
            count = inner_w.count()
            for row in range(count):
                height += inner_w.sizeHintForRow(row)

            # account for spacing between rows
            height += inner_w.spacing() * max(0, count - 1)

            inner_w.setFixedHeight(height)

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
