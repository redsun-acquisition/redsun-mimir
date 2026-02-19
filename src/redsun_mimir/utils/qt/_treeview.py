r"""Descriptor-driven tree view for displaying and editing device settings.

The :class:`DescriptorTreeView` is a self-contained, reusable Qt widget that
renders bluesky-compatible ``describe_configuration`` / ``read_configuration``
dicts as an interactive property tree.

Key layout:

    {name}               (device group row, spans all columns)
    └── {source}         (source group row, e.g. "settings")
        ├── {property}   value   [editor]
        └── …

The ``source`` field of a :class:`~bluesky.protocols.Descriptor` is used as the
sub-group label.  When it carries the ``\\readonly`` suffix
(e.g. ``"settings\\readonly"``) the corresponding value cell is rendered as
plain text and cannot be edited.

Supported ``dtype`` values and their editors
--------------------------------------------
- ``"integer"``  → :class:`~qtpy.QtWidgets.QSpinBox` (optional range via ``limits``)
- ``"number"``   → :class:`~qtpy.QtWidgets.QDoubleSpinBox` (optional range via ``limits``)
- ``"string"``   → :class:`~qtpy.QtWidgets.QLineEdit`, or :class:`~qtpy.QtWidgets.QComboBox`
                   when ``choices`` is present
- ``"boolean"``  → :class:`~qtpy.QtWidgets.QComboBox` with ``True`` / ``False`` entries
- ``"array"``    → read-only label showing the serialised value (no in-place edit)
"""

from __future__ import annotations

import logging
from enum import IntEnum
from typing import TYPE_CHECKING, Any, cast

from qtpy import QtCore, QtGui, QtWidgets
from sunflare.virtual import Signal

if TYPE_CHECKING:
    from bluesky.protocols import Descriptor, Reading
    from event_model.documents import LimitsRange

__all__ = ["DescriptorTreeView", "DescriptorModel"]

_log = logging.getLogger("redsun")

# ---------------------------------------------------------------------------
# Internal enumerations and roles
# ---------------------------------------------------------------------------


class _Col(IntEnum):
    """Column indices."""

    GROUP = 0
    SETTING = 1
    VALUE = 2


class _NodeType(IntEnum):
    """Tree node kinds."""

    ROOT = 0
    GROUP = 1
    SETTING = 2


#: Custom ``ItemDataRole`` used to propagate :class:`_NodeType` to the delegate.
_NodeTypeRole: int = QtCore.Qt.ItemDataRole.UserRole + 1


# ---------------------------------------------------------------------------
# Tree node
# ---------------------------------------------------------------------------


class _Node:
    r"""Lightweight tree node storing either a group label or a setting leaf.

    Parameters
    ----------
    name:
        Display name (``None`` only for the invisible root node).
    parent:
        Parent node (``None`` for root).
    kind:
        Node category (root / group / setting).
    descriptor:
        Bluesky descriptor for setting leaves; ``None`` for group nodes.
    readonly:
        Whether the setting is non-editable.
    full_key:
        Canonical ``name\\property`` key used for readings look-ups;
        set only on setting leaves.
    """

    __slots__ = (
        "_name",
        "_parent",
        "_children",
        "_kind",
        "_descriptor",
        "_readonly",
        "full_key",
    )

    def __init__(
        self,
        name: str | None,
        parent: _Node | None,
        kind: _NodeType,
        *,
        descriptor: Descriptor | None = None,
        readonly: bool = False,
        full_key: str | None = None,
    ) -> None:
        self._name = name
        self._parent = parent
        self._children: list[_Node] = []
        self._kind = kind
        self._descriptor = descriptor
        self._readonly = readonly
        self.full_key: str | None = full_key

    # ------------------------------------------------------------------
    # Child helpers
    # ------------------------------------------------------------------

    def append(self, child: _Node) -> None:
        """Append *child* to this node's children."""
        self._children.append(child)

    def child(self, row: int) -> _Node | None:
        """Return the child at *row*, or ``None`` when out-of-range."""
        return self._children[row] if 0 <= row < len(self._children) else None

    def child_count(self) -> int:
        """Return the number of direct children."""
        return len(self._children)

    def row(self) -> int:
        """Index of this node within its parent's children list."""
        if self._parent:
            return self._parent._children.index(self)
        return 0

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        """Display name (empty string for the invisible root)."""
        return self._name or ""

    @property
    def kind(self) -> _NodeType:
        """Node category."""
        return self._kind

    @property
    def descriptor(self) -> Descriptor | None:
        """Bluesky descriptor (setting leaves only)."""
        return self._descriptor

    @property
    def readonly(self) -> bool:
        """``True`` when editing is disabled for this setting."""
        return self._readonly

    @property
    def parent(self) -> _Node | None:
        """Parent node."""
        return self._parent


# ---------------------------------------------------------------------------
# Delegate — creates editors and handles painting
# ---------------------------------------------------------------------------


class _Delegate(QtWidgets.QStyledItemDelegate):
    """Item delegate that wires dtype-appropriate editors into the value column.

    Supported dtype → editor mappings:

    - ``"integer"``  → ``QSpinBox`` (honours ``limits.control``)
    - ``"number"``   → ``QDoubleSpinBox`` (honours ``limits.control``)
    - ``"string"``   → ``QLineEdit``, or ``QComboBox`` when ``choices`` present
    - ``"boolean"``  → ``QComboBox`` with ``True`` / ``False``
    - ``"array"``    → no editor (read-only display only)
    """

    def createEditor(
        self,
        parent: QtWidgets.QWidget | None,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ) -> QtWidgets.QWidget | None:
        """Return a dtype-appropriate editor widget for *index*."""
        if index.column() != _Col.VALUE:
            return None

        node: _Node = index.internalPointer()
        if node.kind != _NodeType.SETTING or node.readonly or node.descriptor is None:
            return None

        desc = node.descriptor
        dtype: str = desc.get("dtype", "")
        limits = cast(
            "LimitsRange",
            desc.get("limits", {}).get("control", {}),
        )
        low: float | None = limits.get("low", None)
        high: float | None = limits.get("high", None)

        assert parent is not None

        match dtype:
            case "integer":
                sb = QtWidgets.QSpinBox(parent)
                sb.setRange(
                    int(low) if low is not None else -(2**31),
                    int(high) if high is not None else 2**31 - 1,
                )
                sb.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
                sb.setFrame(False)
                return sb

            case "number":
                dsb = QtWidgets.QDoubleSpinBox(parent)
                dsb.setRange(
                    float(low) if low is not None else -1e18,
                    float(high) if high is not None else 1e18,
                )
                dsb.setDecimals(4)
                dsb.setSingleStep(0.1)
                dsb.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
                dsb.setFrame(False)
                return dsb

            case "string":
                choices: list[str] = desc.get("choices", [])
                if choices:
                    cb = QtWidgets.QComboBox(parent)
                    cb.addItems(choices)
                    return cb
                le = QtWidgets.QLineEdit(parent)
                le.setFrame(False)
                return le

            case "boolean":
                cb = QtWidgets.QComboBox(parent)
                cb.addItem("True", True)
                cb.addItem("False", False)
                return cb

            case _:
                # "array" and unknown dtypes: no editor (display-only)
                return None

    def setEditorData(
        self,
        editor: QtWidgets.QWidget | None,
        index: QtCore.QModelIndex,
    ) -> None:
        """Populate *editor* with the current value from the model."""
        m = index.model()
        if m is None:
            super().setEditorData(editor, index)
            return
        value = m.data(index, QtCore.Qt.ItemDataRole.EditRole)

        if isinstance(editor, QtWidgets.QSpinBox):
            if isinstance(value, (int, float)):
                editor.setValue(int(value))
            return

        if isinstance(editor, QtWidgets.QDoubleSpinBox):
            if isinstance(value, (int, float)):
                editor.setValue(float(value))
            return

        if isinstance(editor, QtWidgets.QComboBox):
            node: _Node = index.internalPointer()
            if node.descriptor and node.descriptor.get("dtype") == "boolean":
                idx = editor.findData(bool(value))
            else:
                idx = editor.findText(str(value) if value is not None else "")
            if idx >= 0:
                editor.setCurrentIndex(idx)
            return

        if isinstance(editor, QtWidgets.QLineEdit):
            editor.setText(str(value) if value is not None else "")
            return

        super().setEditorData(editor, index)

    def setModelData(
        self,
        editor: QtWidgets.QWidget | None,
        model: QtCore.QAbstractItemModel | None,
        index: QtCore.QModelIndex,
    ) -> None:
        """Write the editor value back to *model*."""
        if model is None:
            return

        if isinstance(editor, QtWidgets.QSpinBox):
            model.setData(index, editor.value(), QtCore.Qt.ItemDataRole.EditRole)
        elif isinstance(editor, QtWidgets.QDoubleSpinBox):
            model.setData(index, editor.value(), QtCore.Qt.ItemDataRole.EditRole)
        elif isinstance(editor, QtWidgets.QComboBox):
            node: _Node = index.internalPointer()
            if node.descriptor and node.descriptor.get("dtype") == "boolean":
                model.setData(
                    index, editor.currentData(), QtCore.Qt.ItemDataRole.EditRole
                )
            else:
                model.setData(
                    index, editor.currentText(), QtCore.Qt.ItemDataRole.EditRole
                )
        elif isinstance(editor, QtWidgets.QLineEdit):
            model.setData(index, editor.text(), QtCore.Qt.ItemDataRole.EditRole)
        else:
            super().setModelData(editor, model, index)

    def updateEditorGeometry(
        self,
        editor: QtWidgets.QWidget | None,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ) -> None:
        """Constrain the editor to the value cell rectangle."""
        if editor is not None:
            editor.setGeometry(option.rect)
        super().updateEditorGeometry(editor, option, index)

    def paint(
        self,
        painter: QtGui.QPainter | None,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ) -> None:
        """Right-align value cells; centre setting-name cells."""
        if index.column() == _Col.VALUE:
            option.displayAlignment = (
                QtCore.Qt.AlignmentFlag.AlignRight
                | QtCore.Qt.AlignmentFlag.AlignVCenter
            )
        elif index.column() == _Col.SETTING:
            option.displayAlignment = (
                QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter
            )
        super().paint(painter, option, index)


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class DescriptorModel(QtCore.QAbstractItemModel):
    """Qt item model backed by bluesky descriptor and reading dicts.

    The tree hierarchy is::

        {device name}        GROUP row (spans all columns)
        └── {source}         GROUP row (e.g. "settings")
            ├── {property}   SETTING leaf — value shown in Column.VALUE
            └── …

    Parameters
    ----------
    parent:
        Optional parent ``QObject``.

    Signals
    -------
    sigStructureChanged:
        Emitted after :meth:`update_structure` or :meth:`add_setting`
        completes a model reset.
    sigPropertyChanged:
        Emitted from :meth:`setData` when the user commits an edit.
        Carries the full canonical key (``str``) and the new value.
    """

    sigStructureChanged: Signal = Signal()
    sigPropertyChanged: Signal = Signal(str, object)

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._descriptors: dict[str, Descriptor] = {}
        self._readings: dict[str, Any] = {}
        self._pending: dict[str, dict[str, Any]] = {}
        self._root = _Node(None, None, _NodeType.ROOT)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_structure(self, descriptors: dict[str, Descriptor]) -> None:
        r"""Replace the entire descriptor set and rebuild the tree.

        Parameters
        ----------
        descriptors:
            Flat ``describe_configuration()`` dict keyed by
            ``name\\property`` canonical keys.
        """
        self.beginResetModel()
        self._descriptors = descriptors
        self._root = self._build(descriptors)
        self.endResetModel()
        self.sigStructureChanged.emit()

    def add_setting(self, key: str, descriptor: Descriptor) -> None:
        r"""Insert a single additional setting and rebuild the tree.

        Parameters
        ----------
        key:
            Canonical ``name\\property`` key.
        descriptor:
            Bluesky descriptor for the setting.
        """
        self.beginResetModel()
        self._descriptors[key] = descriptor
        self._root = self._build(self._descriptors)
        self.endResetModel()
        self.sigStructureChanged.emit()

    def update_readings(self, readings: dict[str, Reading[Any]]) -> None:
        """Merge *readings* into the local cache and refresh the view.

        Parameters
        ----------
        readings:
            Flat ``read_configuration()`` dict (same key scheme as descriptors).
        """
        for k, v in readings.items():
            self._readings[k] = v["value"]
        self.dataChanged.emit(QtCore.QModelIndex(), QtCore.QModelIndex())

    def update_reading(self, key: str, reading: Reading[Any]) -> None:
        """Update a single setting value and emit a targeted ``dataChanged``.

        Parameters
        ----------
        key:
            Canonical key of the setting to update.
        reading:
            New reading for that setting.
        """
        self._readings[key] = reading["value"]
        node = self._find_leaf(key)
        if node is None:
            return
        row = node.row()
        parent_node = node.parent
        if parent_node is None:
            return
        parent_idx = self.createIndex(parent_node.row(), 0, parent_node)
        idx = self.index(row, _Col.VALUE, parent_idx)
        self.dataChanged.emit(idx, idx)

    def confirm_change(self, key: str, success: bool) -> None:
        """Confirm or revert a pending edit.

        Parameters
        ----------
        key:
            Canonical key of the setting that was attempted.
        success:
            Whether the device accepted the change.  On ``False`` the cached
            value is reverted to the pre-edit value.
        """
        pending = self._pending.pop(key, None)
        if pending is None:
            return
        if not success:
            self._readings[key] = pending["old"]
            self.dataChanged.emit(
                pending["index"],
                pending["index"],
                [QtCore.Qt.ItemDataRole.DisplayRole],
            )
            _log.info("Reverted '%s' to previous value.", key)

    def get_keys(self) -> set[str]:
        """Return the set of all descriptor keys currently in the model."""
        return set(self._descriptors.keys())

    # ------------------------------------------------------------------
    # QAbstractItemModel interface
    # ------------------------------------------------------------------

    def rowCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:  # noqa: B008
        """Return child count of *parent*."""
        if parent.column() > 0:
            return 0
        node: _Node = self._root if not parent.isValid() else parent.internalPointer()
        return node.child_count()

    def columnCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:  # noqa: B008
        """Three columns: Group, Setting, Value."""
        return len(_Col)

    def index(
        self,
        row: int,
        column: int,
        parent: QtCore.QModelIndex = QtCore.QModelIndex(),  # noqa: B008
    ) -> QtCore.QModelIndex:
        """Return the model index for *(row, column)* under *parent*."""
        if not self.hasIndex(row, column, parent):
            return QtCore.QModelIndex()
        parent_node: _Node = (
            self._root if not parent.isValid() else parent.internalPointer()
        )
        child = parent_node.child(row)
        return self.createIndex(row, column, child) if child else QtCore.QModelIndex()

    def parent(self, child: QtCore.QModelIndex) -> QtCore.QModelIndex:  # type: ignore[override]
        """Return the parent index of *child*."""
        if not child.isValid():
            return QtCore.QModelIndex()
        node: _Node = child.internalPointer()
        p = node.parent
        if p is None or p is self._root:
            return QtCore.QModelIndex()
        return self.createIndex(p.row(), 0, p)

    def data(
        self,
        index: QtCore.QModelIndex,
        role: int = QtCore.Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        """Return display / edit / role data for *index*."""
        if not index.isValid():
            return None

        node: _Node = index.internalPointer()
        col = index.column()

        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            if node.kind == _NodeType.GROUP:
                return node.name if col == _Col.GROUP else None
            if node.kind == _NodeType.SETTING:
                if col == _Col.SETTING:
                    return node.name
                if col == _Col.VALUE and node.full_key is not None:
                    raw = self._readings.get(node.full_key)
                    if raw is None:
                        return ""
                    units = node.descriptor.get("units", "") if node.descriptor else ""
                    suffix = f" {units}" if units else ""
                    # For sequences/arrays display a compact repr
                    if isinstance(raw, (list, tuple)):
                        return f"{list(raw)}{suffix}"
                    return f"{raw}{suffix}"
            return None

        if role == QtCore.Qt.ItemDataRole.EditRole:
            if col == _Col.VALUE and node.kind == _NodeType.SETTING and node.full_key:
                return self._readings.get(node.full_key)
            return None

        if role == QtCore.Qt.ItemDataRole.TextAlignmentRole:
            if node.kind == _NodeType.SETTING:
                if col == _Col.VALUE:
                    return (
                        QtCore.Qt.AlignmentFlag.AlignRight
                        | QtCore.Qt.AlignmentFlag.AlignVCenter
                    )
                if col == _Col.SETTING:
                    return (
                        QtCore.Qt.AlignmentFlag.AlignLeft
                        | QtCore.Qt.AlignmentFlag.AlignVCenter
                    )
            return None

        if role == _NodeTypeRole:
            return node.kind

        if role == QtCore.Qt.ItemDataRole.ForegroundRole:
            if node.kind == _NodeType.SETTING and node.readonly:
                return QtGui.QBrush(QtGui.QColor(130, 130, 130))
            return None

        if role == QtCore.Qt.ItemDataRole.ToolTipRole:
            if node.kind == _NodeType.SETTING and node.descriptor:
                desc = node.descriptor
                parts: list[str] = [f"dtype: {desc.get('dtype', '?')}"]
                if "units" in desc:
                    parts.append(f"units: {desc['units']}")
                if node.readonly:
                    parts.append("(read-only)")
                return " | ".join(parts)
            return None

        return None

    def headerData(
        self,
        section: int,
        orientation: QtCore.Qt.Orientation,
        role: int = QtCore.Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        """Column headers: Group, Setting, Value."""
        if orientation != QtCore.Qt.Orientation.Horizontal:
            return None
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return ("Group", "Setting", "Value")[section]
        if role == QtCore.Qt.ItemDataRole.TextAlignmentRole:
            return QtCore.Qt.AlignmentFlag.AlignHCenter
        return None

    def flags(self, index: QtCore.QModelIndex) -> QtCore.Qt.ItemFlag:
        """Editable only for non-readonly value cells."""
        if not index.isValid():
            return QtCore.Qt.ItemFlag.NoItemFlags
        base = QtCore.Qt.ItemFlag.ItemIsEnabled
        node: _Node = index.internalPointer()
        if (
            index.column() == _Col.VALUE
            and node.kind == _NodeType.SETTING
            and not node.readonly
        ):
            base |= (
                QtCore.Qt.ItemFlag.ItemIsEditable | QtCore.Qt.ItemFlag.ItemIsSelectable
            )
        return base

    def setData(
        self,
        index: QtCore.QModelIndex,
        value: Any,
        role: int = QtCore.Qt.ItemDataRole.EditRole,
    ) -> bool:
        """Commit an edit: cache value, emit :attr:`sigPropertyChanged`."""
        if not index.isValid() or role != QtCore.Qt.ItemDataRole.EditRole:
            return False
        node: _Node = index.internalPointer()
        if index.column() != _Col.VALUE or node.kind != _NodeType.SETTING:
            return False
        key = node.full_key
        if key is None or key not in self._readings:
            _log.error("Key '%s' not found in readings.", key)
            return False

        self._pending[key] = {"old": self._readings[key], "index": index}
        self._readings[key] = value
        self.dataChanged.emit(index, index, [QtCore.Qt.ItemDataRole.DisplayRole])
        self.sigPropertyChanged.emit(key, value)
        return True

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build(descriptors: dict[str, Descriptor]) -> _Node:
        r"""Build the tree from *descriptors* and return the new root node.

        Tree structure::

            root
            └── device_name   (GROUP)
                └── source    (GROUP)
                    └── prop  (SETTING)
        """
        root = _Node(None, None, _NodeType.ROOT)
        # groups[device][source] = [(full_key, prop_name, descriptor, readonly)]
        groups: dict[str, dict[str, list[tuple[str, str, Descriptor, bool]]]] = {}

        for full_key, desc in descriptors.items():
            if "\\" in full_key:
                device, prop = full_key.split("\\", 1)
            else:
                device, prop = "", full_key

            source_raw: str = desc.get("source", "unknown")
            source_parts = source_raw.split("\\", 1)
            source = source_parts[0]
            readonly = len(source_parts) > 1 and source_parts[1] == "readonly"

            groups.setdefault(device, {}).setdefault(source, []).append(
                (full_key, prop, desc, readonly)
            )

        for device, source_map in groups.items():
            dev_node = _Node(device, root, _NodeType.GROUP)
            root.append(dev_node)
            for source, leaves in source_map.items():
                src_node = _Node(source, dev_node, _NodeType.GROUP)
                dev_node.append(src_node)
                for full_key, prop, desc, readonly in leaves:
                    leaf = _Node(
                        prop,
                        src_node,
                        _NodeType.SETTING,
                        descriptor=desc,
                        readonly=readonly,
                        full_key=full_key,
                    )
                    src_node.append(leaf)

        return root

    def _find_leaf(self, key: str) -> _Node | None:
        """Return the SETTING leaf whose ``full_key`` matches *key*."""
        for di in range(self._root.child_count()):
            dev = self._root.child(di)
            if dev is None:
                continue
            for si in range(dev.child_count()):
                src = dev.child(si)
                if src is None:
                    continue
                for li in range(src.child_count()):
                    leaf = src.child(li)
                    if leaf is not None and leaf.full_key == key:
                        return leaf
        return None


# ---------------------------------------------------------------------------
# Public view widget
# ---------------------------------------------------------------------------


class DescriptorTreeView(QtWidgets.QTreeView):
    """Self-contained tree widget for browsing and editing device settings.

    Drop this widget into any Qt layout; call :meth:`model` to access the
    underlying :class:`DescriptorModel` for populating data.

    Example
    -------
    ::

        view = DescriptorTreeView(parent)
        view.model().update_structure(device.describe_configuration())
        view.model().update_readings(device.read_configuration())
        view.model().sigPropertyChanged.connect(on_property_changed)

    Parameters
    ----------
    parent:
        Optional parent widget.
    """

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = DescriptorModel(self)
        self._delegate = _Delegate(self)
        self.setModel(self._model)
        self.setItemDelegate(self._delegate)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        # Persistent editors handle all editing — no popup editors needed.
        self.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.header()
        if header is not None:
            header.setStretchLastSection(True)
        self._model.sigStructureChanged.connect(self._on_structure_changed)

    def model(self) -> DescriptorModel:
        """Return the underlying :class:`DescriptorModel`."""
        return self._model

    # ------------------------------------------------------------------
    # Private slots
    # ------------------------------------------------------------------

    def _on_structure_changed(self) -> None:
        """Expand all nodes, open persistent editors, and fit columns."""
        self.expandAll()
        self._apply_spanning()
        self._open_persistent_editors()
        for col in range(self._model.columnCount()):
            self.resizeColumnToContents(col)
        header = self.header()
        if header is not None:
            header.setSectionResizeMode(
                _Col.GROUP, QtWidgets.QHeaderView.ResizeMode.ResizeToContents
            )
            header.setSectionResizeMode(
                _Col.SETTING, QtWidgets.QHeaderView.ResizeMode.Stretch
            )
            header.setSectionResizeMode(
                _Col.VALUE, QtWidgets.QHeaderView.ResizeMode.ResizeToContents
            )

    def _apply_spanning(self) -> None:
        """Span all GROUP rows across all columns."""
        root_idx = QtCore.QModelIndex()
        for dev_row in range(self._model.rowCount(root_idx)):
            dev_idx = self._model.index(dev_row, 0, root_idx)
            self.setFirstColumnSpanned(dev_row, root_idx, True)
            for src_row in range(self._model.rowCount(dev_idx)):
                self.setFirstColumnSpanned(src_row, dev_idx, True)

    def _open_persistent_editors(self) -> None:
        """Open a persistent editor for every non-readonly SETTING value cell."""
        root_idx = QtCore.QModelIndex()
        for dev_row in range(self._model.rowCount(root_idx)):
            dev_idx = self._model.index(dev_row, 0, root_idx)
            for src_row in range(self._model.rowCount(dev_idx)):
                src_idx = self._model.index(src_row, 0, dev_idx)
                for leaf_row in range(self._model.rowCount(src_idx)):
                    leaf_idx = self._model.index(leaf_row, _Col.VALUE, src_idx)
                    node: _Node = leaf_idx.internalPointer()
                    if (
                        node is not None
                        and node.kind == _NodeType.SETTING
                        and not node.readonly
                        and node.descriptor is not None
                        and node.descriptor.get("dtype") not in ("array", "")
                    ):
                        self.openPersistentEditor(leaf_idx)
