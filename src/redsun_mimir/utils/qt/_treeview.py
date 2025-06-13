# mypy: disable-error-code="union-attr"
"""Qt tree model for displaying device properties read from descriptor documents as a hierarchical structure."""

from __future__ import annotations

import logging
from enum import IntEnum
from typing import TYPE_CHECKING, cast

from qtpy.QtCore import QAbstractItemModel, QEvent, QModelIndex, QObject, Qt
from qtpy.QtGui import QPaintEvent, QPalette
from qtpy.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QItemDelegate,
    QSpinBox,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionComboBox,
    QStyleOptionViewItem,
    QStylePainter,
    QTreeView,
    QWidget,
)
from sunflare.virtual import Signal

if TYPE_CHECKING:
    from typing import Any

    from bluesky.protocols import Descriptor, Reading
    from qtpy.QtGui import QPainter


class CenteredComboBoxDelegate(QItemDelegate):
    def paint(
        self,
        painter: QPainter | None,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:
        opt = QStyleOptionViewItem(option)
        opt.displayAlignment = Qt.AlignmentFlag.AlignCenter
        super().paint(painter, opt, index)


class CenteredComboBox(QComboBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # Set the delegate for the dropdown items
        self.view().setItemDelegate(CenteredComboBoxDelegate())

        # Style the view (dropdown list) to center text
        self.view().setStyleSheet("text-align: center;")

    def paintEvent(self, event: QPaintEvent | None) -> None:
        """Override paint event to ensure the selected text is always centered."""
        painter = QStylePainter(self)
        painter.setPen(self.palette().color(QPalette.ColorRole.Text))

        # Draw the combobox frame/button
        opt = QStyleOptionComboBox()
        self.initStyleOption(opt)

        # Save and clear the current text from the style options
        text = opt.currentText
        opt.currentText = ""

        # Draw the control without text
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, opt)

        # Calculate text rectangle
        rect = self.style().subElementRect(
            QStyle.SubElement.SE_ComboBoxFocusRect, opt, self
        )

        # Draw the text centered in the rectangle
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)


class BooleanComboBox(CenteredComboBox):
    """ComboBox for boolean values."""

    ...


class Column(IntEnum):
    """Enumeration of column indices in the tree model."""

    DEVICE = 0
    GROUP = 1
    SETTING = 2
    VALUE = 3


class NodeType(IntEnum):
    """Enumeration of node types in the tree model."""

    ROOT = 0
    DEVICE = 1
    GROUP = 2
    SETTING = 3


#: Custom roles for internal use
NodeTypeRole = Qt.ItemDataRole.UserRole + 1


class TreeNode:
    """Node of the tree model.

    Parameters
    ----------
    name : ``str | None``
        Name of the item
    parent : ``TreeNode | None``
        Parent item
    node_type : ``NodeType``
        Type of node
    data : ``dict | None``, optional
        Data for the device property.
        Default is ``None``.
    descriptor : ``Descriptor | None``
        Descriptor for the device property.
        Default is ``None``.
    readonly : ``bool``, optional
        Whether the property is read-only.
        Default is ``False``.

    """

    def __init__(
        self,
        name: str | None,
        parent: TreeNode | None,
        node_type: NodeType,
        *,
        data: Reading[Any] | None = None,
        descriptor: Descriptor | None = None,
        readonly: bool = False,
    ):
        self._name = name
        self._parent = parent
        self._children: list[TreeNode] = []
        self._node_type = node_type
        self._data = data
        self._descriptor = descriptor
        self._readonly = readonly

    def appendChild(self, child: TreeNode) -> None:
        """Add a child to this item.

        Parameters
        ----------
        child : ``TreeNode``
            Child item to add

        """
        self._children.append(child)

    def child(self, row: int) -> TreeNode | None:
        """Get the child at the specified row.

        Parameters
        ----------
        row : ``int``
            Row index

        Returns
        -------
        ``TreeNode | None``
            Child item at the specified row or None

        """
        if 0 <= row < len(self._children):
            return self._children[row]
        return None

    def childCount(self) -> int:
        """Get the number of children.

        Returns
        -------
        ``int``
            Number of children

        """
        return len(self._children)

    def row(self) -> int:
        """Get the row index of this item within its parent.

        Returns
        -------
        ``int``
            Row index

        """
        if self._parent:
            return self._parent._children.index(self)
        return 0

    def parent(self) -> TreeNode | None:
        """Get the parent item.

        Returns
        -------
        ``TreeNode | None``
            Parent item. None if it's the root item.

        """
        return self._parent

    @property
    def name(self) -> str:
        """The name of the item."""
        return self._name if self._name is not None else ""

    @property
    def node_type(self) -> NodeType:
        """The node type."""
        return self._node_type

    @property
    def data(self) -> Reading[Any] | None:
        """The item reading."""
        return self._data

    @property
    def descriptor(self) -> Descriptor | None:
        """The item descriptor."""
        return self._descriptor

    @property
    def readonly(self) -> bool:
        """Whether the item is read-only."""
        return self._readonly


class DescriptorDelegate(QStyledItemDelegate):
    """Custom descriptor delegate for providing appropriate editors for each setting.

    Parameters
    ----------
    parent : ``QWidget``, optional
        Parent widget

    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

    def paint(
        self,
        painter: QPainter | None,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:
        """Paint the delegate.

        Parameters
        ----------
        painter : ``QPainter``, optional
            Painter to use for drawing
        option : ``QStyleOptionViewItem``
            Style options for rendering
        index : ``QModelIndex``
            Index of the item

        """
        if index.column() == Column.VALUE:
            option.displayAlignment = Qt.AlignmentFlag.AlignHCenter
        if index.column() == Column.SETTING:
            option.displayAlignment = Qt.AlignmentFlag.AlignHCenter

        # Use the default painting for the rest
        super().paint(painter, option, index)

    def createEditor(
        self,
        parent: QWidget | None,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> QWidget:
        """Create an editor for editing the data item.

        Parameters
        ----------
        parent : ``QWidget``
            Parent widget
        option : ``QStyleOptionViewItem``
            Style options
        index : ``QModelIndex``
            Model index

        Returns
        -------
        ``QWidget``
            Editor widget

        """
        assert parent is not None
        # Only create custom editors for the value column
        if index.column() != Column.VALUE:
            return cast("QWidget", super().createEditor(parent, option, index))

        # Get the tree item
        item: TreeNode = index.internalPointer()

        # Only create custom editors for setting nodes
        if item.node_type != NodeType.SETTING:
            return cast("QWidget", super().createEditor(parent, option, index))

        # Get the descriptor directly from the tree item
        descriptor = item.descriptor
        if not descriptor:
            return cast("QWidget", super().createEditor(parent, option, index))

        # Check if this setting has limits
        limits = descriptor.get("limits", {}).get("control", {})  # type: ignore[var-annotated]
        low = limits.get("low", None)
        high = limits.get("high", None)

        editor: QSpinBox | QDoubleSpinBox | CenteredComboBox

        if descriptor["dtype"] in ["integer", "number"]:
            # Create a spin box with the appropriate range
            if descriptor["dtype"] == "integer":
                editor = QSpinBox(parent)
                if low is not None and high is not None:
                    editor.setRange(int(low), int(high))
                editor.setSingleStep(1)
                editor.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            elif descriptor["dtype"] == "number":
                editor = QDoubleSpinBox(parent)
                if low is not None and high is not None:
                    editor.setRange(float(low), float(high))
                editor.setSingleStep(0.1)
                editor.setDecimals(2)
                editor.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            else:
                return cast("QWidget", super().createEditor(parent, option, index))

            return editor

        if descriptor["dtype"] == "string":
            choices: list[str] = descriptor.get("choices", [])
            if choices:
                editor = CenteredComboBox(parent)
                editor.setItemDelegate(CenteredComboBoxDelegate(editor))
                editor.addItems(choices)
                return editor
            else:
                return cast("QWidget", super().createEditor(parent, option, index))
        if descriptor["dtype"] == "boolean":
            editor = BooleanComboBox(parent)
            editor.setItemDelegate(CenteredComboBoxDelegate(editor))
            editor.addItem("True", True)
            editor.addItem("False", False)
            return editor

        return cast("QWidget", super().createEditor(parent, option, index))

    def setEditorData(self, editor: QWidget | None, index: QModelIndex) -> None:
        """Set the data to be edited in the editor.

        Parameters
        ----------
        editor : ``QWidget``
            Editor widget
        index : ``QModelIndex``
            Model index

        """
        # Handle spin boxes
        if isinstance(editor, QSpinBox | QDoubleSpinBox):
            value = index.model().data(index, Qt.ItemDataRole.EditRole)
            if value:
                editor.setValue(value)
                return
        elif isinstance(editor, BooleanComboBox):
            value = index.model().data(index, Qt.ItemDataRole.EditRole)
            if value is not None:
                editor.setCurrentIndex(editor.findData(value))
                return
        elif isinstance(editor, QComboBox):
            value = index.model().data(index, Qt.ItemDataRole.EditRole)
            if value:
                editor.setCurrentIndex(editor.findText(value))
                return

        # Fall back to default implementation
        super().setEditorData(editor, index)

    def editorEvent(
        self,
        event: QEvent | None,
        model: QAbstractItemModel | None,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> bool:
        """Handle events before they are used to update the item.

        Parameters
        ----------
        event : ``QEvent``
            Event to handle
        model : ``QAbstractItemModel``
            Model containing the data
        option : ``QStyleOptionViewItem``
            Style options for rendering
        index : ``QModelIndex``
            Index of the item

        Returns
        -------
        ``bool``
            True if the event was handled, False otherwise

        """
        if index.column() != Column.VALUE:
            return super().editorEvent(event, model, option, index)
        if event.type() == QEvent.Type.MouseButtonPress:
            item: TreeNode = index.internalPointer()
            if item.node_type == NodeType.SETTING and (
                index.flags() & Qt.ItemFlag.ItemIsEditable
            ):
                view = cast("DescriptorTreeView", self.parent())
                view.edit(index)
                return True
        return super().editorEvent(event, model, option, index)

    def setModelData(
        self,
        editor: QWidget | None,
        model: QAbstractItemModel | None,
        index: QModelIndex,
    ) -> None:
        """Set the data from the editor back to the model.

        Parameters
        ----------
        editor : ``QWidget``
            Editor widget
        model : ``QAbstractItemModel``
            Data model
        index : ``QModelIndex``
            Model index

        """
        if isinstance(editor, QSpinBox | QDoubleSpinBox):
            model.setData(index, editor.value(), Qt.ItemDataRole.EditRole)
        elif isinstance(editor, BooleanComboBox):
            model.setData(index, editor.currentData(), Qt.ItemDataRole.EditRole)
        elif isinstance(editor, QComboBox):
            model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)
        else:
            # Fall back to default implementation
            super().setModelData(editor, model, index)


class DescriptorModel(QAbstractItemModel):
    """Tree model for displaying device settings in a hierarchical structure.

    Parameters
    ----------
    parent : ``QObject``, optional
        Parent object.


    Attributes
    ----------
    sigStructureChanged : ``Signal``
        Signal emitted when the model structure changes
        (a new descriptor is added).
    sigPropertyChanged : ``Signal[str, dict[str, Any]]``
        Signal emitted when a property changes its value.

        - ``str``: device name
        - ``dict[str, Any]``: key-value pair of property name and new value

    """

    sigStructureChanged = Signal()
    sigPropertyChanged = Signal(str, object)

    def __init__(self, parent: QObject | None = None):
        """Initialize the model with an empty structure.

        Parameters
        ----------
        parent : object, optional
            Parent object

        """
        super().__init__(parent)
        self._logger = logging.getLogger("redsun")
        self._descriptors: dict[str, dict[str, Descriptor]] = {}
        self._readings: dict[str, dict[str, Reading[Any]]] = {}

        # Build the initial empty tree structure
        self._build_tree()

    def _build_tree(self) -> None:
        self._root_item = TreeNode(None, None, NodeType.ROOT)

        # Add devices from existing descriptor
        for device_name, device_descriptor in self._descriptors.items():
            self._add_device_to_tree(device_name, device_descriptor)

    def _add_device_to_tree(
        self, device_name: str, device_descriptor: dict[str, Descriptor]
    ) -> TreeNode:
        """Add a device to the tree structure.

        Parameters
        ----------
        device_name : ``str``
            Name of the device
        device_descriptor : ``dict[str, Descriptor]``
            Dictionary of device settings and their descriptor

        Returns
        -------
        ``TreeNode``
            The created device tree item

        """
        device_item = TreeNode(device_name, self._root_item, NodeType.DEVICE)
        self._root_item.appendChild(device_item)

        # Group settings by source
        # {source: [(setting_name, setting_data), ...]}
        groups: dict[str, list[tuple[str, Descriptor]]] = {}
        readonly_flags: dict[str, bool] = {}
        for setting_name, setting_data in device_descriptor.items():
            group_tokens = setting_data["source"].split("/")
            group_name = setting_data["source"] = group_tokens[0]
            if len(group_tokens) > 1 and group_tokens[1] == "readonly":
                readonly_flags[setting_name] = True

            if group_name not in groups:
                groups.update({group_name: []})
            groups[group_name].append((setting_name, setting_data))

        # Add groups and their settings
        for group_name, settings in groups.items():
            group_item = TreeNode(group_name, device_item, NodeType.GROUP)
            device_item.appendChild(group_item)
            for setting_name, setting_data in settings:
                try:
                    readonly = readonly_flags[setting_name]
                except KeyError:
                    readonly = False
                setting_item = TreeNode(
                    setting_name,
                    group_item,
                    NodeType.SETTING,
                    descriptor=setting_data,
                    readonly=readonly,
                )
                group_item.appendChild(setting_item)

        return device_item

    def add_device(
        self, device_name: str, device_descriptor: dict[str, Descriptor]
    ) -> None:
        """Add a new device to the model.

        Parameters
        ----------
        device_name : ``str``
            Name of the device
        device_descriptor : ``dict[str, Descriptor]``
            Dictionary of device settings and their descriptor

        """
        if device_name in self._descriptors.keys():
            # Device already exists
            return

        self.beginResetModel()

        # Add to descriptors
        self._descriptors[device_name] = device_descriptor

        # Add to tree
        self._add_device_to_tree(device_name, device_descriptor)

        self.endResetModel()
        self.sigStructureChanged.emit()

    def update_structure(self, descriptor: dict[str, dict[str, Descriptor]]) -> None:
        """Update the entire structure of the model.

        Parameters
        ----------
        descriptor : ``dict[str, dict[str, Descriptor]]``
            Dictionary containing the new descriptor structure

        """
        self.beginResetModel()

        self._descriptors = descriptor
        self._build_tree()

        self.endResetModel()
        self.sigStructureChanged.emit()

    def add_setting(
        self, device_name: str, setting_name: str, setting_data: Descriptor
    ) -> None:
        """Add a new setting to an existing device.

        Parameters
        ----------
        device_name : ``str``
            Name of the device.
        setting_name : ``str``
            Name of the setting.
        setting_data : ``Descriptor``
            Metadata for the setting.

        """
        if device_name not in self._descriptors:
            return

        self.beginResetModel()

        # Add to descriptor
        self._descriptors[device_name][setting_name] = setting_data

        # Rebuild tree
        self._build_tree()

        self.endResetModel()
        self.sigStructureChanged.emit()

    def update_readings(self, device: str, values: dict[str, Reading[Any]]) -> None:
        """Update the values in the model.

        Parameters
        ----------
        device: ``str``
            Name of the device.

        values : ``dict[str, Reading[Any]]``
            Dictionary containing the values to update.

        """
        # Merge with existing values
        if device not in self._readings:
            self._readings[device] = {}

        for setting_name, setting_value in values.items():
            self._readings[device][setting_name] = setting_value["value"]

        # Emit dataChanged for the entire model
        self.dataChanged.emit(QModelIndex(), QModelIndex())

    def update_setting_value(
        self, device_name: str, setting_name: str, value_data: Reading[Any]
    ) -> None:
        """Update a specific setting value.

        Parameters
        ----------
        device_name : str
            Name of the device
        setting_name : str
            Name of the setting
        value_data : dict
            Value data to update

        """
        # Ensure structure exists
        if device_name not in self._readings:
            self._readings[device_name] = {}

        self._readings[device_name][setting_name] = value_data["value"]

        # Find the item in the tree to emit a specific dataChanged signal
        device_item = self._find_device_item(device_name)
        if device_item:
            setting_item = self._find_setting_item(device_item, setting_name)
            if setting_item:
                row = setting_item.row()
                parent_index = self.createIndex(
                    setting_item.parent().row(), 0, setting_item.parent()
                )
                index = self.index(row, Column.VALUE, parent_index)
                self.dataChanged.emit(index, index)

    def _find_device_item(self, device_name: str) -> TreeNode | None:
        """Find a device item by name.

        Parameters
        ----------
        device_name : ``str``
            Name of the device to find

        Returns
        -------
        ``TreeNode | None``
            The device item if found, otherwise None

        """
        for i in range(self._root_item.childCount()):
            child = self._root_item.child(i)
            if child.name == device_name:
                return child
        return None

    def _find_setting_item(
        self, device_item: TreeNode, setting_name: str
    ) -> TreeNode | None:
        """Find a setting item within a device by name.

        Parameters
        ----------
        device_item : ``TreeNode``
            The device item to search in
        setting_name : ``str``
            Name of the setting to find

        Returns
        -------
        ``TreeNode | None``
            The setting item if found, otherwise None

        """
        # Check all groups
        for group_idx in range(device_item.childCount()):
            group_item = device_item.child(group_idx)
            # Check all settings in this group
            for setting_idx in range(group_item.childCount()):
                setting_item = group_item.child(setting_idx)
                if setting_item.name == setting_name:
                    return setting_item
        return None

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """Return the number of rows under the given parent.

        Parameters
        ----------
        parent : ``QModelIndex``, optional
            The parent index

        Returns
        -------
        ``int``
            Number of rows

        """
        if parent.column() > 0:
            return 0

        if not parent.isValid():
            parent_item = self._root_item
        else:
            parent_item = parent.internalPointer()

        return parent_item.childCount()

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """Return the number of columns in the model.

        Parameters
        ----------
        parent : ``QModelIndex``, optional
            The parent index (not used).

        Returns
        -------
        ``int``
            Number of columns

        """
        return len(Column)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """Return the data stored under the given role for the item referenced by the index.

        Parameters
        ----------
        index : ``QModelIndex``
            The index to query
        role : ``int``, optional
            The role to query

        Returns
        -------
        ``Any``
            The requested data

        """
        if not index.isValid():
            return None

        item: TreeNode = index.internalPointer()
        column = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            # Display data based on column and node type
            node_type = item.node_type

            if column == Column.DEVICE:
                return item.name if node_type == NodeType.DEVICE else ""
            elif column == Column.GROUP:
                return item.name if node_type == NodeType.GROUP else ""
            elif column == Column.SETTING:
                return item.name if node_type == NodeType.SETTING else ""
            elif column == Column.VALUE:
                if node_type == NodeType.SETTING:
                    device_name = item.parent().parent().name
                    setting_name = item.name

                    # Try to get the value from the values dictionary
                    if (
                        device_name in self._readings
                        and setting_name in self._readings[device_name]
                    ):
                        # Get the value and format it with units if available
                        value = self._readings[device_name][setting_name]

                        # Get units from the item's metadata
                        units = ""
                        metadata = item.descriptor
                        if metadata and "units" in metadata:
                            units = f" {metadata['units']}"

                        return f"{value}{units}"
                    return ""
                return ""

        elif role == NodeTypeRole:
            return item.node_type

        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        """Return the header data for the given role and section.

        Parameters
        ----------
        section : int
            Column or row number
        orientation : Qt.Orientation
            Header orientation
        role : int, optional
            Data role

        Returns
        -------
        object
            Header data

        """
        if orientation == Qt.Orientation.Horizontal:
            if role == Qt.ItemDataRole.DisplayRole:
                headers = ["Device", "Group", "Setting", "Value"]
                return headers[section]
            elif role == Qt.ItemDataRole.TextAlignmentRole:
                return Qt.AlignmentFlag.AlignHCenter
        return None

    def index(
        self, row: int, column: int, parent: QModelIndex = QModelIndex()
    ) -> QModelIndex:
        """Return the index of the item in the model specified by the given row, column and parent index.

        Parameters
        ----------
        row : int
            Row number
        column : int
            Column number
        parent : QModelIndex, optional
            Parent index

        Returns
        -------
        QModelIndex
            Model index for the specified item

        """
        if not self.hasIndex(row, column, parent):
            return QModelIndex()

        if not parent.isValid():
            parent_item = self._root_item
        else:
            parent_item = parent.internalPointer()

        child_item = parent_item.child(row)
        if child_item:
            return self.createIndex(row, column, child_item)
        return QModelIndex()

    def parent(self, child: QModelIndex) -> QModelIndex:  # type: ignore
        """Return the parent of the model item with the given index.

        Parameters
        ----------
        child : ``QModelIndex``
            Index of the child item

        Returns
        -------
        ``QModelIndex``
            Index of the parent item

        """
        if not child.isValid():
            return QModelIndex()

        child_item: TreeNode = child.internalPointer()
        parent_item = child_item.parent()

        if parent_item == self._root_item or parent_item is None:
            return QModelIndex()

        # Create index for parent
        return self.createIndex(parent_item.row(), 0, parent_item)

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        """Return the item flags for the given index.

        Parameters
        ----------
        index : QModelIndex
            Model index

        Returns
        -------
        Qt.ItemFlag
            Item flags

        """
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags

        flags = Qt.ItemFlag.ItemIsEnabled

        # If it's a value cell, make it editable
        item: TreeNode = index.internalPointer()
        if index.column() == Column.VALUE and item.node_type == NodeType.SETTING:
            if not item.readonly:
                flags |= Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsSelectable

        return flags

    def setData(
        self,
        index: QModelIndex,
        value: Any,
        role: int = Qt.ItemDataRole.EditRole,
    ) -> bool:
        """Set the role data for the item at index to value.

        Parameters
        ----------
        index : ``QModelIndex``
            Model index.
        value : ``Any``
            New value.
        role : ``int``, optional
            Data role.
            Default is ``Qt.ItemDataRole.EditRole``.

        Returns
        -------
        ``bool``
            True if successful

        """
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False

        item: TreeNode = index.internalPointer()

        if index.column() == Column.VALUE and item.node_type == NodeType.SETTING:
            device_name = item.parent().parent().name
            setting_name = item.name

            # the assumption is that the settings is pre-emptively
            # provided by a descriptor document; hence, if
            # the device name or setting name is not found in the
            # descriptor, the setting is not valid and an error is raised
            # Ensure the structure exists
            if device_name not in self._readings:
                self._logger.error(f"Device '{device_name}' not found in the model.")
                return False
            if setting_name not in self._readings[device_name]:
                self._logger.error(
                    f"Setting '{setting_name}' not found in device '{device_name}'."
                )
                return False

            # Update the value
            try:
                self._readings[device_name][setting_name] = value
                self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole])
                self.sigPropertyChanged.emit(device_name, {setting_name: value})
                return True
            except Exception as e:
                self._logger.exception(f"Error updating setting value: {e}")
                return False

        return False

    def get_devices(self) -> list[str]:
        """Get a list of all device names in the model.

        Returns
        -------
        ``list[str]``
            list of device names

        """
        return list(self._descriptors.keys())

    def get_settings(self, device_name: str) -> set[str]:
        """Get a set of all setting names for a device.

        Parameters
        ----------
        device_name : ``str``
            Name of the device

        Returns
        -------
        ``set[str]``
            set of setting names

        """
        if device_name not in self._descriptors:
            return set()
        return set(self._descriptors[device_name].keys())


class DescriptorTreeView(QTreeView):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = DescriptorModel(self)
        self._delegate = DescriptorDelegate(self)
        self.setModel(self._model)
        self.setItemDelegate(self._delegate)
        self.setAlternatingRowColors(True)

    def model(self) -> DescriptorModel:
        return self._model
