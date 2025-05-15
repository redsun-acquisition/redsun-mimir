from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, cast

from napari._qt.layer_controls.qt_image_controls import QtImageControls
from napari._qt.widgets.qt_mode_buttons import QtModeRadioButton
from napari.utils.translations import trans
from qtpy.QtWidgets import QButtonGroup, QFormLayout, QGridLayout

from ._common import Mode

if TYPE_CHECKING:
    from ._layer import DetectorLayer


class DetectorLayerControls(QtImageControls):  # type: ignore[misc]
    """Custom controls for the DetectorLayer."""

    MODE: ClassVar[type[Mode]] = Mode
    RESIZE_ACTION_NAME: ClassVar[str] = "activate_image_resize_mode"
    layer: DetectorLayer

    def __init__(self, layer: DetectorLayer) -> None:
        super().__init__(layer)

        self.button_group = QButtonGroup(self)
        self.panzoom_button = self._radio_button(
            layer,
            "pan",
            self.MODE.PAN_ZOOM,
            False,
            self.PAN_ZOOM_ACTION_NAME,
            extra_tooltip_text=trans._("\n(or hold Space)\n(hold Shift to pan in 3D)"),
            checked=True,
        )
        self.transform_button = self._radio_button(
            layer,
            "transform",
            self.MODE.TRANSFORM,
            True,
            self.TRANSFORM_ACTION_NAME,
            extra_tooltip_text=trans._(
                "\nAlt + Left mouse click over this button to reset"
            ),
        )
        self.resize_button = QtModeRadioButton(
            layer=layer,
            button_name="resize",
            mode=self.MODE.RESIZE,
            tooltip="Set the current portion of layer to visualize",
        )
        self.resize_button.clicked.connect(self._on_resize_button_clicked)
        self.button_group.addButton(self.resize_button)
        self._MODE_BUTTONS[self.MODE.RESIZE] = self.resize_button
        self._EDIT_BUTTONS += (self.resize_button,)

        self.button_grid = QGridLayout()
        self.button_grid.addWidget(self.resize_button, 0, 5)
        self.button_grid.addWidget(self.panzoom_button, 0, 6)
        self.button_grid.addWidget(self.transform_button, 0, 7)
        self.button_grid.setContentsMargins(5, 0, 0, 5)
        self.button_grid.setColumnStretch(0, 1)
        self.button_grid.setSpacing(4)

        cast("QFormLayout", self.layout()).removeRow(0)
        cast("QFormLayout", self.layout()).insertRow(0, self.button_grid)

    def _on_resize_button_clicked(self, checked: bool) -> None:
        self.layer.bounding_box.visible = checked
        self.layer.roi.visible = checked
