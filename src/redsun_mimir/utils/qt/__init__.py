# mypy: disable-error-code="union-attr"
from __future__ import annotations

from qtpy import QtWidgets

from ._treeview import DescriptorTreeView

__all__ = ["InfoDialog", "DescriptorTreeView"]


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
        text: str | None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.setWindowTitle(title)
        self.resize(500, 300)

        layout = QtWidgets.QVBoxLayout(self)

        self.text_edit = QtWidgets.QTextEdit()
        self.text_edit.setReadOnly(True)
        if text is None:
            text = "No information available."
        self.text_edit.setText(text)
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
        cls, title: str, text: str | None, parent: QtWidgets.QWidget | None = None
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
