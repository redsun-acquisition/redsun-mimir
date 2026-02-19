# mypy: disable-error-code="union-attr,attr-defined"
from __future__ import annotations

import logging
from enum import IntEnum
from typing import TYPE_CHECKING, cast

from qtpy import QtCore, QtGui, QtWidgets
from sunflare.virtual import Signal

if TYPE_CHECKING:
    from typing import Any

    from bluesky.protocols import Descriptor, Reading
    from event_model.documents import LimitsRange


class CenteredComboBoxDelegate(QtWidgets.QItemDelegate):
    def paint(
        self,
        painter: QtGui.QPainter | None,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ) -> None:
        opt = QtWidgets.QStyleOptionViewItem(option)
        opt.displayAlignment = QtCore.Qt.AlignmentFlag.AlignCenter
        super().paint(painter, opt, index)


class CenteredComboBox(QtWidgets.QComboBox):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)

        # Set the delegate for the dropdown items
        self.view().setItemDelegate(CenteredComboBoxDelegate())

        # Style the view (dropdown list) to center text
        self.view().setStyleSheet("text-align: center;")

    def paintEvent(self, _: QtGui.QPaintEvent | None) -> None:
        """Override paint event to ensure the selected text is always centered."""
        painter = QtWidgets.QStylePainter(self)
        painter.setPen(self.palette().color(QtGui.QPalette.ColorRole.Text))

        # Draw the combobox frame/button
        opt = QtWidgets.QStyleOptionComboBox()
        self.initStyleOption(opt)

        # Save and clear the current text from the style options
        text = opt.currentText
        opt.currentText = ""

        # Draw the control without text
        painter.drawComplexControl(QtWidgets.QStyle.ComplexControl.CC_ComboBox, opt)

        # Calculate text rectangle
        rect = self.style().subElementRect(
            QtWidgets.QStyle.SubElement.SE_ComboBoxFocusRect, opt, self
        )

        # Draw the text centered in the rectangle
        painter.drawText(rect, QtCore.Qt.AlignmentFlag.AlignCenter, text)


class BooleanComboBox(CenteredComboBox):
    """ComboBox for boolean values."""

    ...


class Column(IntEnum):
    """Enumeration of column indices in the tree model."""

    GROUP = 0
    SETTING = 1
    VALUE = 2


class NodeType(IntEnum):
    """Enumeration of node types in the tree model."""

    ROOT = 0
    GROUP = 1
    SETTING = 2


#: Custom roles for internal use
NodeTypeRole = QtCore.Qt.ItemDataRole.UserRole + 1


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
        self._full_key: str | None = (
            None  # Store full key for settings with device prefix
        )

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


class DescriptorDelegate(QtWidgets.QStyledItemDelegate):
    """Custom descriptor delegate for providing appropriate editors for each setting.

    Parameters
    ----------
    parent : ``QtWidgets.QWidget``, optional
        Parent widget

    """

    def __init__(self, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)

    def paint(
        self,
        painter: QtGui.QPainter | None,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
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
            option.displayAlignment = QtCore.Qt.AlignmentFlag.AlignHCenter
        if index.column() == Column.SETTING:
            option.displayAlignment = QtCore.Qt.AlignmentFlag.AlignHCenter

        # Use the default painting for the rest
        super().paint(painter, option, index)

    def createEditor(
        self,
        parent: QtWidgets.QWidget | None,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ) -> QtWidgets.QWidget:
        """Create an editor for editing the data item.

        Parameters
        ----------
        parent : ``QtWidgets.QWidget``
            Parent widget
        option : ``QStyleOptionViewItem``
            Style options
        index : ``QModelIndex``
            Model index

        Returns
        -------
        ``QtWidgets.QWidget``
            Editor widget

        """
        assert parent is not None
        # Only create custom editors for the value column
        if index.column() != Column.VALUE:
            return cast(
                "QtWidgets.QWidget", super().createEditor(parent, option, index)
            )

        # Get the tree item
        item: TreeNode = index.internalPointer()

        # Only create custom editors for setting nodes
        if item.node_type != NodeType.SETTING:
            return cast(
                "QtWidgets.QWidget", super().createEditor(parent, option, index)
            )

        # Get the descriptor directly from the tree item
        descriptor = item.descriptor
        if not descriptor:
            return cast(
                "QtWidgets.QWidget", super().createEditor(parent, option, index)
            )

        # Check if this setting has limits
        limits = cast("LimitsRange", descriptor.get("limits", {}).get("control", {}))
        low = limits.get("low", None)
        high = limits.get("high", None)

        editor: QtWidgets.QSpinBox | QtWidgets.QDoubleSpinBox | CenteredComboBox

        if descriptor["dtype"] in ["integer", "number"]:
            # Create a spin box with the appropriate range
            if descriptor["dtype"] == "integer":
                editor = QtWidgets.QSpinBox(parent)
                if low is not None and high is not None:
                    editor.setRange(int(low), int(high))
                editor.setSingleStep(1)
                editor.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
            elif descriptor["dtype"] == "number":
                editor = QtWidgets.QDoubleSpinBox(parent)
                if low is not None and high is not None:
                    editor.setRange(float(low), float(high))
                editor.setSingleStep(0.1)
                editor.setDecimals(2)
                editor.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
            else:
                return cast(
                    "QtWidgets.QWidget", super().createEditor(parent, option, index)
                )

            return editor

        if descriptor["dtype"] == "string":
            choices: list[str] = descriptor.get("choices", [])
            if choices:
                editor = CenteredComboBox(parent)
                editor.setItemDelegate(CenteredComboBoxDelegate(editor))
                editor.addItems(choices)
                return editor
            else:
                return cast(
                    "QtWidgets.QWidget", super().createEditor(parent, option, index)
                )
        if descriptor["dtype"] == "boolean":
            editor = BooleanComboBox(parent)
            editor.setItemDelegate(CenteredComboBoxDelegate(editor))
            editor.addItem("True", True)
            editor.addItem("False", False)
            return editor

        return cast("QtWidgets.QWidget", super().createEditor(parent, option, index))

    def setEditorData(
        self, editor: QtWidgets.QWidget | None, index: QtCore.QModelIndex
    ) -> None:
        """Set the data to be edited in the editor.

        Parameters
        ----------
        editor : ``QtWidgets.QWidget``
            Editor widget
        index : ``QModelIndex``
            Model index

        """
        # Handle spin boxes
        if isinstance(editor, QtWidgets.QSpinBox | QtWidgets.QDoubleSpinBox):
            value = index.model().data(index, QtCore.Qt.ItemDataRole.EditRole)
            if value:
                editor.setValue(value)
                return
        elif isinstance(editor, BooleanComboBox):
            value = index.model().data(index, QtCore.Qt.ItemDataRole.EditRole)
            if value is not None:
                editor.setCurrentIndex(editor.findData(value))
                return
        elif isinstance(editor, QtWidgets.QComboBox):
            value = index.model().data(index, QtCore.Qt.ItemDataRole.EditRole)
            if value:
                editor.setCurrentIndex(editor.findText(value))
                return

        # Fall back to default implementation
        super().setEditorData(editor, index)

    def editorEvent(
        self,
        event: QtCore.QEvent | None,
        model: QtCore.QAbstractItemModel | None,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
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
        if event.type() == QtCore.QEvent.Type.MouseButtonPress:
            item: TreeNode = index.internalPointer()
            if item.node_type == NodeType.SETTING and (
                index.flags() & QtCore.Qt.ItemFlag.ItemIsEditable
            ):
                view = cast("DescriptorTreeView", self.parent())
                view.edit(index)
                return True
        return super().editorEvent(event, model, option, index)

    def setModelData(
        self,
        editor: QtWidgets.QWidget | None,
        model: QtCore.QAbstractItemModel | None,
        index: QtCore.QModelIndex,
    ) -> None:
        """Set the data from the editor back to the model.

        Parameters
        ----------
        editor : ``QtWidgets.QWidget``
            Editor widget
        model : ``QAbstractItemModel``
            Data model
        index : ``QModelIndex``
            Model index

        """
        if isinstance(editor, QtWidgets.QSpinBox | QtWidgets.QDoubleSpinBox):
            model.setData(index, editor.value(), QtCore.Qt.ItemDataRole.EditRole)
        elif isinstance(editor, BooleanComboBox):
            model.setData(index, editor.currentData(), QtCore.Qt.ItemDataRole.EditRole)
        elif isinstance(editor, QtWidgets.QComboBox):
            model.setData(index, editor.currentText(), QtCore.Qt.ItemDataRole.EditRole)
        else:
            # Fall back to default implementation
            super().setModelData(editor, model, index)


class DescriptorModel(QtCore.QAbstractItemModel):
    """Tree model for displaying device settings in a hierarchical structure.

    Parameters
    ----------
    parent : ``QObject``, optional
        Parent object


    Attributes
    ----------
    sigStructureChanged : ``Signal``
        Signal emitted when the model structure changes
        (a new descriptor is added).
    sigPropertyChanged : ``Signal[str, dict[str, Any]]``
        Signal emitted when a property changes its value.
        - ``str``: setting name
        - ``dict[str, Any]``: key-value pair of property name and new value

    """

    sigStructureChanged = Signal()
    sigPropertyChanged = Signal(str, object)

    def __init__(self, parent: QtCore.QObject | None = None):
        """Initialize the model with an empty structure.

        Parameters
        ----------
        parent : object, optional
            Parent object

        """
        super().__init__(parent)
        self._logger = logging.getLogger("redsun")
        self._descriptors: dict[str, Descriptor] = {}
        self._readings: dict[str, Reading[Any]] = {}
        # Add pending changes storage
        self._pending_changes: dict[str, dict[str, Any]] = {}

        # Build the initial empty tree structure
        self._build_tree()

    def _build_tree(self) -> None:
        self._root_item = TreeNode(None, None, NodeType.ROOT)

        # Add settings from existing descriptor
        self._add_settings_to_tree(self._descriptors)

    def _add_settings_to_tree(self, device_descriptor: dict[str, Descriptor]) -> None:
        r"""Add settings to the tree structure.

        Keys are expected in the canonical form ``{name}\\{property}``.
        The tree is built as a two-level hierarchy::

            {name}               (device node)
            └── {source}         (source group node, e.g. "settings")
                └── {property}   (setting leaf node)

        Parameters
        ----------
        device_descriptor : ``dict[str, Descriptor]``
            Dictionary of device settings and their descriptor.

        """
        # outer: device name → inner: source → list of (full_key, property, descriptor)
        groups: dict[str, dict[str, list[tuple[str, str, Descriptor]]]] = {}
        readonly_flags: dict[str, bool] = {}

        for full_key, descriptor in device_descriptor.items():
            # Parse key into device name and property name
            if "\\" in full_key:
                device_label, property_name = full_key.split("\\", 1)
            else:
                device_label = ""
                property_name = full_key

            # Extract source and readonly flag (separated by "\" instead of "/")
            source_raw = descriptor.get("source", "unknown")
            source_parts = source_raw.split("\\", 1)
            source = source_parts[0]
            if len(source_parts) > 1 and source_parts[1] == "readonly":
                readonly_flags[full_key] = True

            groups.setdefault(device_label, {}).setdefault(source, []).append(
                (full_key, property_name, descriptor)
            )

        # Build tree: Device → Source → Setting
        for device_label, source_groups in groups.items():
            device_item = TreeNode(device_label, self._root_item, NodeType.GROUP)
            self._root_item.appendChild(device_item)

            for source, settings in source_groups.items():
                source_item = TreeNode(source, device_item, NodeType.GROUP)
                device_item.appendChild(source_item)

                for full_key, property_name, descriptor in settings:
                    readonly = readonly_flags.get(full_key, False)
                    setting_item = TreeNode(
                        property_name,
                        source_item,
                        NodeType.SETTING,
                        descriptor=descriptor,
                        readonly=readonly,
                    )
                    setting_item._full_key = full_key
                    source_item.appendChild(setting_item)

    def update_structure(self, descriptor: dict[str, Descriptor]) -> None:
        """Update the entire structure of the model.

        Parameters
        ----------
        descriptor : ``dict[str, Descriptor]``
            Dictionary containing the new descriptor structure

        """
        self.beginResetModel()

        self._descriptors = descriptor
        self._build_tree()

        self.endResetModel()
        self.sigStructureChanged.emit()

    def add_setting(self, setting_name: str, setting_data: Descriptor) -> None:
        """Add a new setting to the device.

        Parameters
        ----------
        setting_name : ``str``
            Name of the setting.
        setting_data : ``Descriptor``
            Metadata for the setting.

        """
        self.beginResetModel()

        # Add to descriptor
        self._descriptors[setting_name] = setting_data

        # Rebuild tree
        self._build_tree()

        self.endResetModel()
        self.sigStructureChanged.emit()

    def update_readings(self, values: dict[str, Reading[Any]]) -> None:
        """Update the values in the model.

        Parameters
        ----------
        values : ``dict[str, Reading[Any]]``
            Dictionary containing the values to update.

        """
        # Merge with existing values
        for setting_name, setting_value in values.items():
            self._readings[setting_name] = setting_value["value"]

        # Emit dataChanged for the entire model
        self.dataChanged.emit(QtCore.QModelIndex(), QtCore.QModelIndex())

    def update_setting_reading(self, setting_name: str, reading: Reading[Any]) -> None:
        """Update a specific setting value.

        Parameters
        ----------
        setting_name : str
            Name of the setting.
        reading : Reading[Any]
            New reading data for the setting.

        """
        self._readings[setting_name] = reading["value"]

        # Find the item in the tree to emit a specific dataChanged signal
        setting_item = self._find_setting_item(setting_name)
        if setting_item:
            row = setting_item.row()
            parent_index = self.createIndex(
                setting_item.parent().row(), 0, setting_item.parent()
            )
            index = self.index(row, Column.VALUE, parent_index)
            self.dataChanged.emit(index, index)

    def _find_setting_item(self, setting_name: str) -> TreeNode | None:
        r"""Find a setting item by its full key.

        Parameters
        ----------
        setting_name : ``str``
            Full canonical key (e.g. ``"MM:mmcore\\exposure"``).

        Returns
        -------
        ``TreeNode | None``
            The matching leaf node, or ``None`` if not found.

        """
        # Tree is three levels deep: device → source → setting
        for device_idx in range(self._root_item.childCount()):
            device_item = self._root_item.child(device_idx)
            for source_idx in range(device_item.childCount()):
                source_item = device_item.child(source_idx)
                for setting_idx in range(source_item.childCount()):
                    setting_item = source_item.child(setting_idx)
                    full_key = getattr(setting_item, "_full_key", setting_item.name)
                    if full_key == setting_name or setting_item.name == setting_name:
                        return setting_item
        return None

    def rowCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:
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

    def columnCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:
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

    def data(
        self, index: QtCore.QModelIndex, role: int = QtCore.Qt.ItemDataRole.DisplayRole
    ) -> Any:
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

        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            node_type = item.node_type

            if column == Column.GROUP:
                return item.name if node_type == NodeType.GROUP else ""
            elif column == Column.SETTING:
                return item.name if node_type == NodeType.SETTING else ""
            elif column == Column.VALUE:
                if node_type == NodeType.SETTING:
                    # Use full key for lookups
                    full_key = getattr(item, "_full_key", item.name)
                    if full_key in self._readings:
                        value = self._readings[full_key]
                        units = ""
                        if item.descriptor and "units" in item.descriptor:
                            units = f" {item.descriptor['units']}"
                        return f"{value}{units}"
                    return ""
                return ""

        elif role == QtCore.Qt.ItemDataRole.EditRole:
            if column == Column.VALUE and item.node_type == NodeType.SETTING:
                full_key = getattr(item, "_full_key", item.name)
                return self._readings.get(full_key, None)

        elif role == NodeTypeRole:
            return item.node_type

        return None

    def headerData(
        self,
        section: int,
        orientation: QtCore.Qt.Orientation,
        role: int = QtCore.Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        """Return the header data for the given role and section.

        Parameters
        ----------
        section : int
            Column or row number
        orientation : QtCore.Qt.Orientation
            Header orientation
        role : int, optional
            Data role

        Returns
        -------
        object
            Header data

        """
        if orientation == QtCore.Qt.Orientation.Horizontal:
            if role == QtCore.Qt.ItemDataRole.DisplayRole:
                headers = ["Group", "Setting", "Value"]
                return headers[section]
            elif role == QtCore.Qt.ItemDataRole.TextAlignmentRole:
                return QtCore.Qt.AlignmentFlag.AlignHCenter
        return None

    def index(
        self, row: int, column: int, parent: QtCore.QModelIndex = QtCore.QModelIndex()
    ) -> QtCore.QModelIndex:
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
            return QtCore.QModelIndex()

        if not parent.isValid():
            parent_item = self._root_item
        else:
            parent_item = parent.internalPointer()

        child_item = parent_item.child(row)
        if child_item:
            return self.createIndex(row, column, child_item)
        return QtCore.QModelIndex()

    def parent(self, child: QtCore.QModelIndex) -> QtCore.QModelIndex:  # type: ignore
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
            return QtCore.QModelIndex()

        child_item: TreeNode = child.internalPointer()
        parent_item = child_item.parent()

        if parent_item == self._root_item or parent_item is None:
            return QtCore.QModelIndex()

        # Create index for parent
        return self.createIndex(parent_item.row(), 0, parent_item)

    def flags(self, index: QtCore.QModelIndex) -> QtCore.Qt.ItemFlag:
        """Return the item flags for the given index.

        Parameters
        ----------
        index : QModelIndex
            Model index

        Returns
        -------
        QtCore.Qt.ItemFlag
            Item flags

        """
        if not index.isValid():
            return QtCore.Qt.ItemFlag.NoItemFlags

        flags = QtCore.Qt.ItemFlag.ItemIsEnabled

        # If it's a value cell, make it editable
        item: TreeNode = index.internalPointer()
        if index.column() == Column.VALUE and item.node_type == NodeType.SETTING:
            if not item.readonly:
                flags |= (
                    QtCore.Qt.ItemFlag.ItemIsEditable
                    | QtCore.Qt.ItemFlag.ItemIsSelectable
                )

        return flags

    def setData(
        self,
        index: QtCore.QModelIndex,
        value: Any,
        role: int = QtCore.Qt.ItemDataRole.EditRole,
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
            Default is ``QtCore.Qt.ItemDataRole.EditRole``.

        Returns
        -------
        ``bool``
            True if successful

        """
        if not index.isValid() or role != QtCore.Qt.ItemDataRole.EditRole:
            return False

        item: TreeNode = index.internalPointer()

        if index.column() == Column.VALUE and item.node_type == NodeType.SETTING:
            # Use full key for lookups
            full_key = getattr(item, "_full_key", item.name)

            if full_key not in self._readings:
                self._logger.error(f"Setting '{full_key}' not found in the model.")
                return False

            # Store the pending change
            old_value = self._readings[full_key]
            self._pending_changes[full_key] = {
                "old_value": old_value,
                "new_value": value,
                "index": index,
            }

            # Update the value temporarily
            try:
                self._readings[full_key] = value
                self.dataChanged.emit(
                    index, index, [QtCore.Qt.ItemDataRole.DisplayRole]
                )

                # Emit the property change signal with full key for the presenter to handle
                self.sigPropertyChanged.emit(full_key, value)
                return True
            except Exception as e:
                self._logger.exception(f"Error updating setting value: {e}")
                return False

        return False

    def confirm_change(self, setting_name: str, success: bool) -> None:
        """Confirm or reject the change.

        Parameters
        ----------
        setting_name : str
            Name of the setting that was changed
        success : bool
            Whether the change was successful

        """
        if setting_name not in self._pending_changes:
            return

        pending = self._pending_changes[setting_name]

        if not success:
            # Revert the change
            self._readings[setting_name] = pending["old_value"]
            self.dataChanged.emit(
                pending["index"], pending["index"], [QtCore.Qt.ItemDataRole.DisplayRole]
            )
            self._logger.info(f"Reverted setting '{setting_name}' to previous value")

        # Clear the pending change
        del self._pending_changes[setting_name]

    def get_settings(self) -> set[str]:
        """Get a set of all setting names.

        Returns
        -------
        ``set[str]``
            set of setting names

        """
        return set(self._descriptors.keys())


class DescriptorTreeView(QtWidgets.QTreeView):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = DescriptorModel(self)
        self._delegate = DescriptorDelegate(self)
        self.setModel(self._model)
        self.setItemDelegate(self._delegate)
        self.setAlternatingRowColors(True)

    def model(self) -> DescriptorModel:
        return self._model
