# mypy: disable-error-code="union-attr"
from __future__ import annotations

from typing import TYPE_CHECKING, cast

from qtpy import QtGui, QtWidgets
from qtpy.QtCore import QEvent, Qt
from qtpy.QtGui import QStandardItemModel

from ._treeview import DescriptorTreeView

if TYPE_CHECKING:
    from collections.abc import Iterable
    from typing import Any

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

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
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

    def addItem(self, item: str | None) -> None:  # type: ignore[override]
        """Add a checkable item to the combobox.

        Parameters
        ----------
        item : ``str``
            The item to add.

        """
        item_obj = QtGui.QStandardItem(item)
        item_obj.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        item_obj.setCheckState(Qt.CheckState.Checked)
        self.model().appendRow(item_obj)

    def addItems(self, items: Iterable[str | None]) -> None:
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

    def paintEvent(self, event: QEvent | None) -> None:
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


class ConfigurationGroupBox(QtWidgets.QGroupBox):
    def layout(self) -> QtWidgets.QFormLayout:
        return cast(QtWidgets.QFormLayout, super().layout())

    def configuration(self) -> dict[str, Any]:
        """Return the current configuration content of the group box.

        Returns
        -------
        ``dict[str, Any]``
            The configuration content.

        """
        configs: dict[str, Any] = {}
        for i in range(self.layout().rowCount()):
            label = cast(
                QtWidgets.QLayoutItem,
                self.layout().itemAt(i, QtWidgets.QFormLayout.ItemRole.LabelRole),
            ).widget()
            widget = cast(
                QtWidgets.QLayoutItem,
                self.layout().itemAt(i, QtWidgets.QFormLayout.ItemRole.FieldRole),
            ).widget()
            assert isinstance(label, QtWidgets.QLabel)
            key = label.text()
            value: bool | str | list[str]
            if isinstance(widget, QtWidgets.QCheckBox):
                value = widget.isChecked()
            elif isinstance(widget, CheckableComboBox):
                value = widget.checkedItems()
            elif isinstance(widget, QtWidgets.QLineEdit):
                value = widget.text()
            elif isinstance(widget, QtWidgets.QPushButton):
                if widget.isCheckable():
                    value = widget.isChecked()
                else:
                    # skip the pushbutton if it is not checkable
                    continue
            else:
                raise NotImplementedError("Unsupported widget type")
            configs.update({key: value})
        return configs


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
