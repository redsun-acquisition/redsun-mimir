from __future__ import annotations

from typing import TYPE_CHECKING

from qtpy import QtGui, QtWidgets
from qtpy.QtCore import QEvent, Qt
from qtpy.QtGui import QStandardItemModel

from ._treeview import DescriptorTreeView

if TYPE_CHECKING:
    from typing import Iterable, Optional

__all__ = ["CheckableComboBox", "InfoDialog", "DescriptorTreeView"]


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

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super(CheckableComboBox, self).__init__(parent)
        self._model = QStandardItemModel(0, 1)
        self._model.dataChanged.connect(lambda: self.repaint())
        self.setModel(self._model)

    def model(self) -> QStandardItemModel:
        """Get the combobox model.

        Returns
        -------
        ``QStandardItemModel``
            The combobox model.

        """
        return self._model

    def addItem(self, item: Optional[str]) -> None:  # type: ignore[override]
        """Add a checkable item to the combobox.

        Parameters
        ----------
        item : ``str``
            The item to add.

        """
        super().addItem(item)
        item_obj = self._model.item(self.count(), 0)
        assert item_obj is not None
        item_obj.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        item_obj.setCheckState(Qt.CheckState.Unchecked)

    def addItems(self, items: Iterable[Optional[str]]) -> None:
        """Add multiple checkable items to the combobox.

        Parameters
        ----------
        items : ``Iterable[str]``
            The items to add.
        """
        for item in items:
            self.addItem(item)

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

    def paintEvent(self, event: Optional[QEvent]) -> None:
        """Repaint the combobox.

        Parameters
        ----------
        event : ``QEvent``, optional
            The event to handle (unused).

        """
        num_checked = len(self.checkedItems())
        item_alias = "item" if num_checked == 1 else "items"

        opt = QtWidgets.QStyleOptionComboBox()
        self.initStyleOption(opt)
        opt.currentText = f"{num_checked} {item_alias} selected"

        painter = QtWidgets.QStylePainter(self)
        painter.setPen(self.palette().color(QtGui.QPalette.ColorRole.Text))
        painter.drawComplexControl(QtWidgets.QStyle.ComplexControl.CC_ComboBox, opt)
        painter.drawControl(QtWidgets.QStyle.ControlElement.CE_ComboBoxLabel, opt)


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
