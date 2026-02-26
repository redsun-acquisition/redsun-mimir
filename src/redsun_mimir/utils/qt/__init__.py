"""Qt utilities for redsun-mimir.

Public surface
--------------
create_param_widget
    Build a single magicgui widget from a ``ParamDescription``.
create_plan_widget
    Build a complete ``PlanWidget`` from a ``PlanSpec``.
ActionButton
    ``QPushButton`` subclass carrying ``Action`` metadata.
PlanWidget
    Frozen dataclass owning all Qt widgets for one plan.
InfoDialog
    Modal dialog that renders Markdown text.
DescriptorTreeView
    Tree view for bluesky descriptor dicts.
"""

from __future__ import annotations

from qtpy import QtWidgets

from redsun_mimir.utils.qt._plan_widget import (
    ActionButton,
    PlanWidget,
    create_plan_widget,
)
from redsun_mimir.utils.qt._treeview import DescriptorTreeView
from redsun_mimir.utils.qt._widget_factory import CompactSelect, create_param_widget

__all__ = [
    "ActionButton",
    "CompactSelect",
    "DescriptorTreeView",
    "InfoDialog",
    "PlanWidget",
    "create_param_widget",
    "create_plan_widget",
]


class InfoDialog(QtWidgets.QDialog):
    """Dialog to provide information to the user.

    Parameters
    ----------
    title : str
        The title of the dialog window.
    text : str
        The text to display in the text edit area (rendered as Markdown).
    parent : QtWidgets.QWidget | None, optional
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
        title : str
            The title of the dialog window.
        text : str
            The text to display in the text edit area.
        parent : QtWidgets.QWidget | None, optional
            The parent widget, by default ``None``.

        Returns
        -------
        int
            Dialog result code (``QDialog.Accepted`` or ``QDialog.Rejected``).
        """
        dialog = cls(title, text, parent)
        return dialog.exec()
