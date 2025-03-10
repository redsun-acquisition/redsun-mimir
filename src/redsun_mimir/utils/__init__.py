from typing import TYPE_CHECKING, Optional

from qtpy.QtCore import Qt
from qtpy.QtWidgets import QComboBox

if TYPE_CHECKING:
    from qtpy.QtGui import QStandardItemModel


class CheckableComboBox(QComboBox):
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

    def __init__(self, title: str, parent: Optional[QComboBox] = None) -> None:
        super(CheckableComboBox, self).__init__(parent)
        self._model: QStandardItemModel = self.model() # type: ignore
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
        item_obj = self._model.item(self.count()-1, 0)
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