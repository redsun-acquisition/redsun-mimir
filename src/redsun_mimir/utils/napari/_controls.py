from __future__ import annotations

from typing import TYPE_CHECKING, cast

from napari._qt.layer_controls.qt_image_controls import QtImageControls
from napari._qt.widgets.qt_mode_buttons import QtModePushButton
from qtpy.QtWidgets import QFormLayout, QGridLayout

if TYPE_CHECKING:
    from ._layer import DetectorLayer


class DetectorLayerControls(QtImageControls):  # type: ignore[misc]
    """Custom controls for the DetectorLayer."""

    layer: DetectorLayer

    def __init__(self, layer: DetectorLayer) -> None:
        super().__init__(layer)

        self.resize_button = QtModePushButton(
            layer=layer,
            button_name="resize",
            tooltip="Set the current portion of layer to visualize",
        )
        self.resize_button.setCheckable(True)
        self.resize_button.setChecked(False)
        self.resize_button.toggled[bool].connect(self._on_resize_button_toggled)

        self.button_grid = QGridLayout()
        self.button_grid.addWidget(self.resize_button, 0, 5)
        self.button_grid.addWidget(self.panzoom_button, 0, 6)
        self.button_grid.addWidget(self.transform_button, 0, 7)
        self.button_grid.setContentsMargins(5, 0, 0, 5)
        self.button_grid.setColumnStretch(0, 1)
        self.button_grid.setSpacing(4)

        cast("QFormLayout", self.layout()).removeRow(0)
        cast("QFormLayout", self.layout()).insertRow(0, self.button_grid)

    def _on_resize_button_toggled(self, checked: bool) -> None:
        self.layer.bounding_box.visible = checked
        self.layer.roi.visible = checked
