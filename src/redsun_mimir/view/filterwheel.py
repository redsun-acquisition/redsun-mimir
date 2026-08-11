"""View for filter wheel position control."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from qtpy import QtCore, QtWidgets
from redsun.log import Loggable
from redsun.view import ViewPosition
from redsun.view.qt import QtView
from redsun.virtual import Signal

if TYPE_CHECKING:
    from bluesky.protocols import Descriptor, Reading
    from redsun.virtual import VirtualContainer


class FilterWheelView(QtView, Loggable):
    """View for filter wheel position selection via drop-down.

    Builds one group box per filter wheel device showing available
    labels in a combo box.

    Parameters
    ----------
    name : str
        Identity key of the view.

    Attributes
    ----------
    sigFilterWheelChange : Signal[str, str]
        Emitted when the user selects a new filter position.
        Carries device label and the target label string.
    """

    sigFilterWheelChange = Signal(str, str)

    @property
    def view_position(self) -> ViewPosition:
        return ViewPosition.RIGHT

    def __init__(self, name: str, /) -> None:
        super().__init__(name)
        self.setWindowTitle("Filter Wheel")
        self.main_layout = QtWidgets.QVBoxLayout()
        self._groups: dict[str, QtWidgets.QGroupBox] = {}
        self._combos: dict[str, QtWidgets.QComboBox] = {}

    def register_providers(self, container: VirtualContainer) -> None:
        container.register_signals(self)

    def inject_dependencies(self, container: VirtualContainer) -> None:
        readings: dict[str, Reading[Any]] = container.fw_readings()
        description: dict[str, Descriptor] = container.fw_description()
        self.setup_ui(readings, description)

    def setup_ui(
        self,
        readings: dict[str, Reading[Any]],
        description: dict[str, Descriptor],
    ) -> None:
        for key in readings:
            name = key.split("-")[0] if "-" in key else key
            break
        else:
            return

        layout = QtWidgets.QVBoxLayout()
        self._groups[name] = QtWidgets.QGroupBox(name)
        self._groups[name].setAlignment(
            QtCore.Qt.AlignmentFlag.AlignHCenter
            | QtCore.Qt.AlignmentFlag.AlignRight
        )

        labels_str = readings.get(f"{name}-labels", {}).get("value", "{}")
        if isinstance(labels_str, str):
            import json
            try:
                labels_map = json.loads(labels_str)
            except (json.JSONDecodeError, TypeError):
                labels_map = {}
        else:
            labels_map = labels_str if isinstance(labels_str, dict) else {}

        label_items: list[tuple[str, str]] = []
        for pos_str, text in sorted(labels_map.items(), key=lambda x: int(x[0])):
            label_items.append((f"[{pos_str}] {text}", text))

        combo = QtWidgets.QComboBox()
        for display, _ in label_items:
            combo.addItem(display)
        combo.currentIndexChanged.connect(
            lambda idx: self._on_combo_changed(idx, name, label_items)
        )
        self._combos[name] = combo

        pos_label = QtWidgets.QLabel("Position:")
        layout.addWidget(pos_label)
        layout.addWidget(combo)
        self._groups[name].setLayout(layout)
        self.main_layout.addWidget(self._groups[name])
        self.setLayout(self.main_layout)

    def _on_combo_changed(
        self, index: int, device_name: str, items: list[tuple[str, str]]
    ) -> None:
        if index < 0 or index >= len(items):
            return
        _, label = items[index]
        self.logger.debug("Filter wheel %s -> %s", device_name, label)
        self.sigFilterWheelChange.emit(device_name, label)
