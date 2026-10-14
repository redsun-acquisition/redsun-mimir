"""Tests for Qt view widgets."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import numpy as np
import pytest
from napari._app_model import get_app_model
from napari.layers import LayerLock
from napari.layers._layer_actions import _are_bounding_boxes_visible
from qtpy import QtCore, QtWidgets
from redsun.view.qt.builtins import LogView

from redsun_mimir.common import Roi
from redsun_mimir.hooks import NapariApplication
from redsun_mimir.view.detector import DetectorView
from redsun_mimir.view.image import ROI_BOX, ImageView, place, roi_from_bounds
from redsun_mimir.view.logs import LogsAction

from .conftest import needs_opengl

if TYPE_CHECKING:
    from collections.abc import Iterator

    from bluesky.protocols import Reading
    from qtpy.QtCore import QCoreApplication

    from .conftest import FakeDetector

pytestmark = pytest.mark.qt


@pytest.fixture
def parent(qapp: QCoreApplication) -> QtWidgets.QWidget:
    """Return a widget for a view to be built in."""
    return QtWidgets.QWidget()


def open_logs() -> list[LogView]:
    """Return every log window on screen."""
    return [
        widget
        for widget in QtWidgets.QApplication.topLevelWidgets()
        if isinstance(widget, LogView) and widget.isVisible()
    ]


@pytest.mark.parametrize(
    ("frame_shape", "origin", "fits"),
    [
        ((2, 3), (1, 1), True),
        ((4, 6), (0, 0), True),
        ((2, 3), (4, 1), False),
        ((5, 6), (0, 0), False),
    ],
    ids=["inside", "whole", "past-the-edge", "too-tall"],
)
def test_a_frame_lands_in_its_rectangle(
    frame_shape: tuple[int, int], origin: tuple[int, int], fits: bool
) -> None:
    """Place a frame in its rectangle of a canvas the sensor's size, and refuse one that does not fit."""
    canvas = np.zeros((4, 6), dtype=np.uint8)
    frame = np.ones(frame_shape, dtype=np.uint8)

    assert place(canvas, frame, origin) is fits

    x, y = origin
    height, width = frame_shape
    if fits:
        assert canvas.sum() == height * width
        assert canvas[y : y + height, x : x + width].all()
    else:
        assert not canvas.any()


@pytest.mark.parametrize(
    ("bounds", "expected"),
    [
        (((0, 0), (4, 6)), Roi(0, 0, 6, 4)),
        (((1.2, 1.6), (3.4, 4.5)), Roi(2, 1, 2, 2)),
        (((3.4, 4.5), (1.2, 1.6)), Roi(2, 1, 2, 2)),
        (((-2, -3), (9, 9)), Roi(0, 0, 6, 4)),
        (((2, 2), (2, 2)), Roi(2, 2, 1, 1)),
        (((5, 7), (5, 7)), Roi(5, 3, 1, 1)),
    ],
    ids=["whole", "rounded", "reversed", "clamped", "collapsed", "outside"],
)
def test_a_box_becomes_a_roi_on_the_sensor(
    bounds: tuple[tuple[float, float], tuple[float, float]], expected: Roi
) -> None:
    """Turn a box with (y, x) corners into whole pixels inside a 6 by 4 sensor."""
    assert roi_from_bounds(bounds, (4, 6)) == expected


class TestDetectorViewRoi:
    """Tests for the ROI panel: what the user confirms is what the camera gets."""

    @pytest.fixture
    async def view(
        self, parent: QtWidgets.QWidget, fake_detector: FakeDetector
    ) -> DetectorView:
        view = DetectorView("det_widget", parent)
        view.setup_ui(
            await fake_detector.describe_configuration(),
            await fake_detector.read_configuration(),
        )
        return view

    def test_a_locked_detector_disables_its_editors_and_roi_panel(
        self, view: DetectorView
    ) -> None:
        """Disable the editors and the ROI panel of a locked detector, and enable them again once freed."""
        settings = view.settings_controls["cam"]
        panel = settings.roi_panel
        assert panel is not None
        editors = settings.tree_view.findChildren(QtWidgets.QAbstractSpinBox)
        assert editors

        view.set_locked(frozenset({"cam"}))
        assert not panel.isEnabled()
        assert not any(editor.isEnabled() for editor in editors)

        view.set_locked(frozenset())
        assert panel.isEnabled()
        assert all(editor.isEnabled() for editor in editors)

    def test_ok_sends_the_drawn_region_unchanged(self, view: DetectorView) -> None:
        """Send the drawn region unchanged when OK is pressed."""
        sent: list[tuple[str, str, Any]] = []
        view.sig_property_changed.connect(lambda *args: sent.append(args))
        panel = view.settings_controls["cam"].roi_panel
        assert panel is not None
        panel.select_button.click()
        assert not panel.ok_button.isEnabled()

        view.on_roi_drawn("cam", Roi(1, 1, 3, 2))
        assert panel.pending == Roi(1, 1, 3, 2)
        assert panel.ok_button.isEnabled()
        panel.ok_button.click()

        assert sent == [("cam", "roi", "1,1,3,2")]
        assert not panel.select_button.isChecked()

    def test_select_roi_opens_the_editor_and_asks_the_image_for_a_box(
        self, view: DetectorView
    ) -> None:
        """Open the editor on Select ROI and ask the image for a box, then close both."""
        asked: list[tuple[str, bool]] = []
        view.sig_roi_selection.connect(lambda *args: asked.append(args))
        panel = view.settings_controls["cam"].roi_panel
        assert panel is not None
        assert panel.editor.isHidden()

        panel.select_button.click()
        assert not panel.editor.isHidden()
        panel.select_button.click()
        assert panel.editor.isHidden()

        assert asked == [("cam", True), ("cam", False)]

    def test_an_edit_reaches_the_image_and_stays_inside_the_sensor(
        self, view: DetectorView
    ) -> None:
        """Move the box with the spin boxes, and shrink what fits when a corner moves in."""
        edited: list[tuple[str, Roi]] = []
        view.sig_roi_edited.connect(lambda *args: edited.append(args))
        panel = view.settings_controls["cam"].roi_panel
        assert panel is not None
        panel.select_button.click()

        panel.x_box.setValue(4)

        assert edited == [("cam", Roi(4, 0, 2, 4))]
        assert panel.width_box.maximum() == 2

    def test_full_then_ok_sends_the_whole_sensor(self, view: DetectorView) -> None:
        """Send the whole sensor after Full then OK."""
        sent: list[tuple[str, str, Any]] = []
        view.sig_property_changed.connect(lambda *args: sent.append(args))
        panel = view.settings_controls["cam"].roi_panel
        assert panel is not None
        view.on_new_configuration("cam", "cam-roi", "1,1,3,2")
        panel.select_button.click()

        panel.full_button.click()
        panel.ok_button.click()

        assert sent == [("cam", "roi", "0,0,6,4")]

    def test_an_applied_region_is_shown_and_needs_no_ok(
        self, view: DetectorView
    ) -> None:
        """Show a region the camera applied, with OK disabled."""
        panel = view.settings_controls["cam"].roi_panel
        assert panel is not None
        panel.select_button.click()
        view.on_roi_drawn("cam", Roi(1, 1, 3, 2))

        view.on_new_configuration("cam", "cam-roi", "1,1,3,2")

        assert panel.applied == Roi(1, 1, 3, 2)
        assert not panel.ok_button.isEnabled()


@needs_opengl
def test_the_layer_panel_cannot_be_dragged_away(parent: QtWidgets.QWidget) -> None:
    """Keep the layer panel on screen when its splitter is dragged to the edge."""
    view = ImageView("image_view", parent)
    view.resize(900, 600)
    view.show()
    splitter = view.findChild(
        QtWidgets.QSplitter, options=QtCore.Qt.FindChildOption.FindDirectChildrenOnly
    )
    try:
        assert splitter is not None
        splitter.setSizes([0, 900])
        QtWidgets.QApplication.processEvents()

        assert splitter.sizes()[0] > 0
    finally:
        view.shutdown()
        view.close()


@needs_opengl
def test_a_new_layer_is_logged_one_setting_per_line(
    parent: QtWidgets.QWidget, caplog: pytest.LogCaptureFixture
) -> None:
    """Log the layer made for a detector with each of its settings on a line."""
    view = ImageView("image_view", parent)
    caplog.set_level(logging.DEBUG, logger="redsun")
    try:
        view.setup_layers({"cam": {"shape": (4, 6), "dtype": "uint8"}})
    finally:
        view.shutdown()
        view.close()

    messages = [record.getMessage() for record in caplog.records]
    first = messages.index("Creating layer for cam:")
    assert messages[first + 1 : first + 3] == ["  shape: (4, 6)", "  dtype: uint8"]


@needs_opengl
class TestImageViewRoi:
    """Tests for the selection box on a detector's layer."""

    @pytest.fixture
    def view(self, parent: QtWidgets.QWidget) -> Iterator[ImageView]:
        view = ImageView("image_view", parent)
        view.setup_layers({"cam": {"shape": (4, 6), "dtype": "uint8"}})
        try:
            yield view
        finally:
            view.shutdown()
            view.close()

    def test_dragging_the_box_announces_a_roi_and_changes_nothing_else(
        self, view: ImageView
    ) -> None:
        """Announce the ROI a dragged box covers."""
        drawn: list[tuple[str, Roi]] = []
        view.sig_roi_drawn.connect(lambda name, roi: drawn.append((name, roi)))

        view.viewer_model.layers["cam"]._overlays[ROI_BOX].bounds = ((1, 1), (3, 4))

        assert drawn == [("cam", Roi(1, 1, 3, 2))]

    def test_the_box_is_hidden_until_a_selection_is_asked_for(
        self, view: ImageView
    ) -> None:
        """Hide the box until a selection is asked for."""
        box = view.viewer_model.layers["cam"]._overlays[ROI_BOX]
        assert not box.visible

        view.set_roi_selection("cam", True)
        assert box.visible
        view.set_roi_selection("cam", False)
        assert not box.visible

    def test_the_layer_menu_finds_the_embedded_layers(self, view: ImageView) -> None:
        """Find the embedded layers from the layer list's context menu."""
        view.viewer_model.layers.selection.active = view.viewer_model.layers["cam"]

        visible = get_app_model().injection_store.inject(_are_bounding_boxes_visible)

        assert visible() is False

    def test_a_frame_not_shaped_like_its_roi_is_dropped(self, view: ImageView) -> None:
        """Drop a frame not shaped like its ROI, as a monitor first reports one."""
        layer = view.viewer_model.layers["cam"]

        view.update_layers(
            {
                "cam-roi": {"value": Roi(1, 1, 3, 2), "timestamp": 0.0},
                "cam-buffer": {
                    "value": np.full((4, 6), 9, dtype=np.uint8),
                    "timestamp": 0.0,
                },
            }
        )

        assert not layer.data.any()

    def test_a_frame_of_a_new_dtype_retypes_its_layer(self, view: ImageView) -> None:
        """Retype the layer for a frame of a new dtype instead of casting it."""
        layer = view.viewer_model.layers["cam"]
        assert layer.data.dtype == np.uint8

        view.update_layers(
            {
                "cam-roi": {"value": Roi(0, 0, 6, 4), "timestamp": 0.0},
                "cam-buffer": {
                    "value": np.full((4, 6), 1000, dtype=np.uint16),
                    "timestamp": 0.0,
                },
            }
        )

        assert layer.data.dtype == np.uint16
        assert layer.data[0, 0] == 1000

    def test_the_box_follows_an_edit_in_the_panel(self, view: ImageView) -> None:
        """Move the box to an ROI edited in the panel without announcing it back."""
        drawn: list[tuple[str, Roi]] = []
        view.sig_roi_drawn.connect(lambda name, roi: drawn.append((name, roi)))

        view.set_roi_box("cam", Roi(2, 1, 3, 2))

        assert view.viewer_model.layers["cam"]._overlays[ROI_BOX].bounds == (
            (1, 2),
            (3, 5),
        )
        assert drawn == []

    def test_a_detector_layer_is_locked_against_deletion(self, view: ImageView) -> None:
        """Keep a detector's layer when the user deletes it."""
        layers = view.viewer_model.layers
        layers.selection = {layers["cam"]}

        layers.remove_selected()

        assert "cam" in layers
        assert layers["cam"].locked == LayerLock.DELETION

    def test_a_derived_layer_is_plain_and_unlocked(self, view: ImageView) -> None:
        """Show a derived frame on a plain layer with no lock and no box."""
        frame = np.ones((4, 6), dtype=np.float32)

        view.update_layers({"cam_median": {"value": frame, "timestamp": 0.0}})

        layer = view.viewer_model.layers["cam_median"]
        assert not layer.locked
        assert ROI_BOX not in layer._overlays
        np.testing.assert_array_equal(layer.data, frame)

    def test_a_deleted_layer_comes_back_with_its_box_and_takes_frames(
        self, view: ImageView
    ) -> None:
        """Bring a deleted layer back with its box and take frames on it."""
        view.set_roi_selection("cam", True)
        view.set_roi_box("cam", Roi(1, 1, 3, 2))
        view.viewer_model.layers.remove("cam")

        frame = np.full((2, 3), 9, dtype=np.uint8)
        frame.flags.writeable = False
        reading: dict[str, Reading[Any]] = {
            "cam-roi": {"value": Roi(1, 1, 3, 2), "timestamp": 0.0},
            "cam-buffer": {"value": frame, "timestamp": 0.0},
        }
        view.update_layers(reading)
        view.update_layers(reading)

        layer = view.viewer_model.layers["cam"]
        assert layer.locked == LayerLock.DELETION
        assert layer.data.shape == (4, 6)
        assert layer.data[1:3, 1:4].all()
        assert layer.data[0].sum() == 0
        box = layer._overlays[ROI_BOX]
        assert box.visible
        assert box.bounds == ((1, 1), (3, 4))

    def test_an_applied_roi_moves_the_box_and_blanks_the_layer(
        self, view: ImageView
    ) -> None:
        """Move the box and blank the layer when an ROI is applied, and leave both on another setting."""
        drawn: list[tuple[str, Roi]] = []
        view.sig_roi_drawn.connect(lambda name, roi: drawn.append((name, roi)))

        layer = view.viewer_model.layers["cam"]
        layer.data = np.full(layer.data.shape, 7, dtype=layer.data.dtype)

        view.on_new_configuration("cam", "cam-exposure", 5.0)
        assert layer.data.max() == 7
        view.on_new_configuration("cam", "cam-roi", "2,1,3,2")

        box = layer._overlays[ROI_BOX]
        assert box.bounds == ((1, 2), (3, 5))
        assert drawn == []
        assert not layer.data.any()


def test_the_logs_open_in_a_window_of_their_own(parent: QtWidgets.QWidget) -> None:
    """Open one log window, bring it forward when asked again, and a new one once closed."""
    action = LogsAction("logs", parent)

    action.trigger()
    first = open_logs()
    action.trigger()
    assert open_logs() == first and len(first) == 1

    first[0].close()
    QtWidgets.QApplication.sendPostedEvents(
        None, QtCore.QEvent.Type.DeferredDelete.value
    )
    assert open_logs() == []

    action.trigger()
    reopened = open_logs()
    assert len(reopened) == 1
    reopened[0].close()


@needs_opengl
class TestImageViewTheme:
    """Tests for styling the embedded napari viewer."""

    def test_it_carries_no_stylesheet_of_its_own(
        self, parent: QtWidgets.QWidget
    ) -> None:
        """Carry no stylesheet, so the application's one styles the view."""
        view = ImageView("image_view", parent)

        try:
            assert view.styleSheet() == ""
            assert view._qt_viewer.styleSheet() == ""
        finally:
            view.shutdown()
            view.close()


class TestNapariApplication:
    """Tests for the hook that runs the session on napari's application."""

    def test_it_supplies_naparis_application(self, qapp: QCoreApplication) -> None:
        """Return the application napari runs on."""
        assert NapariApplication().create_application([]) is qapp
