from typing import TYPE_CHECKING, Optional

from qtpy import QtWidgets
from qtpy.QtCore import Qt

if TYPE_CHECKING:
    from qtpy.QtGui import QStandardItemModel


class CheckableComboBox(QtWidgets.QComboBox):
    """A QComboBox with checkable items.

    The combo box adds an additional, unselectable
    title item at the top of the list.

    Parameters
    ----------
    title : ``str``
        The title of the combobox.
    parent : ``Optional[QComboBox]``, optional
        The parent widget, by default None

    """

    def __init__(self, title: str, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super(CheckableComboBox, self).__init__(parent)
        self._model: QStandardItemModel = self.model()  # type: ignore
        assert self._model is not None
        self._addTitleItem(title)

    def addCheckableItem(self, item: str) -> None:
        """Add a checkable item to the combobox.

        Parameters
        ----------
        item : ``str``
            The item to add.

        """
        super().addItem(item)
        item_obj = self._model.item(self.count() - 1, 0)
        assert item_obj is not None
        item_obj.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        item_obj.setCheckState(Qt.CheckState.Unchecked)

    def _addTitleItem(self, item: str) -> None:
        super().addItem(item)
        # should be the first index in the combobox and not checkable or selectable
        item_obj = self._model.item(0, 0)
        assert item_obj is not None
        item_obj.setFlags(Qt.ItemFlag.ItemIsEnabled)
        item_obj.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)

    def itemChecked(self, index: int) -> bool:
        """Check if an item is checked.

        Parameters
        ----------
        index : ``int``
            The index of the item to check.

        Returns
        -------
        ``bool``
            True if the item is checked, False otherwise.

        """
        item = self._model.item(index, 0)
        assert item is not None
        return item.checkState() == Qt.CheckState.Checked

    def checkedItems(self) -> list[str]:
        """Get a list of checked items.

        Returns
        -------
        ``List[str]``
            A list of checked items.

        """
        return [self.itemText(i) for i in range(self.count()) if self.itemChecked(i)]


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
        text: Optional[str],
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)

        # Set dialog properties
        self.setWindowTitle(title)
        self.resize(500, 300)

        # Create layout
        layout = QtWidgets.QVBoxLayout(self)

        # Create text edit widget
        self.text_edit = QtWidgets.QTextEdit()
        self.text_edit.setReadOnly(True)  # Make it read-only
        if text is None:
            text = "No information available."
        self.text_edit.setText(text)
        layout.addWidget(self.text_edit)

        # Create OK button
        self.ok_button = QtWidgets.QPushButton("OK")
        self.ok_button.setDefault(True)
        self.ok_button.clicked.connect(self.accept)

        # Add button to a horizontal layout for better positioning
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(self.ok_button)
        layout.addLayout(button_layout)

        self.setLayout(layout)

    @classmethod
    def show_dialog(
        cls, title: str, text: Optional[str], parent: Optional[QtWidgets.QWidget] = None
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
