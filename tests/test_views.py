"""Tests for Qt view widgets."""

from __future__ import annotations

import gc
from typing import TYPE_CHECKING, Any, cast

import numpy as np
import pytest
from bluesky.utils import MsgGenerator
from event_model import DocumentRouter
from napari._app_model import get_app_model
from napari.layers import LayerLock
from napari.layers._layer_actions import _are_bounding_boxes_visible
from napari.settings import get_settings
from qtpy import QtWidgets
from redsun.engine.actions import PlanAction, continuous
from redsun.path_provider import SessionPathProvider

from redsun_mimir.common import Roi
from redsun_mimir.hooks import FONT_SIZE, NapariApplication
from redsun_mimir.presenter.light import LightPresenter
from redsun_mimir.presenter.motor import MotorPresenter
from redsun_mimir.utils.napari import stylesheet
from redsun_mimir.view.acquisition import AcquisitionView
from redsun_mimir.view.detector import DetectorView
from redsun_mimir.view.image import ROI_BOX, ImageView, place, roi_from_bounds
from redsun_mimir.view.light import LightView
from redsun_mimir.view.motor import MotorView

from .conftest import needs_opengl

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from bluesky.protocols import Reading
    from qtpy.QtCore import QCoreApplication
    from qtpy.QtWidgets import QApplication
    from redsun import PlanEntry

    from redsun_mimir.device._mocks import MockLightDevice

    from .conftest import FakeDetector, FakeXYStage

pytestmark = pytest.mark.qt


def _reading(key: str, value: float) -> dict[str, Reading[Any]]:
    """Build the one-entry reading dict a signal subscription delivers."""
    return {key: {"value": value, "timestamp": 0.0}}


#: A toggle action of the stream plan below.
STREAM = PlanAction(name="stream", toggle_states=("start", "stop"))

#: A clicked action of the stream plan below.
SNAP = PlanAction(name="snap")

#: A document callback no plan lists.
VIEWER = DocumentRouter()


class Plans:
    """Offers two continuous plans; `scan` carries a callback of its own."""

    def __init__(self, own: DocumentRouter) -> None:
        self.own = own

    @continuous
    def stream(
        self, frames: int = 1, stream: PlanAction = STREAM, snap: PlanAction = SNAP
    ) -> MsgGenerator[None]:
        yield from ()

    @continuous
    def scan(self, frames: int = 1) -> MsgGenerator[None]:
        yield from ()

    def plan_map(self) -> dict[str, PlanEntry]:
        return {
            "stream": {"plan": self.stream},
            "scan": {"plan": self.scan, "callbacks": [self.own]},
        }


@pytest.fixture
def parent(qapp: QCoreApplication) -> QtWidgets.QWidget:
    """Return a widget for a view to be built in."""
    return QtWidgets.QWidget()


def build_motor_view(widget: MotorView, motor: FakeXYStage) -> None:
    """Build *widget* from a presenter describing *motor*."""
    widget.setup(MotorPresenter("motor_ctrl", devices={motor.name: motor}))


def build_light_view(widget: LightView, *devices: MockLightDevice) -> None:
    """Build *widget* from a presenter describing *devices*."""
    widget.setup(LightPresenter("light_ctrl", devices={d.name: d for d in devices}))


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
    """The canvas keeps the sensor's size; a frame that does not fit is refused."""
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
    """Corners are (y, x); the ROI is whole pixels inside a 6 by 4 sensor."""
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
        """The box follows the spin boxes; a corner moved in shrinks what fits."""
        edited: list[tuple[str, Roi]] = []
        view.sig_roi_edited.connect(lambda *args: edited.append(args))
        panel = view.settings_controls["cam"].roi_panel
        assert panel is not None
        panel.select_button.click()

        panel.x_box.setValue(4)

        assert edited == [("cam", Roi(4, 0, 2, 4))]
        assert panel.width_box.maximum() == 2

    def test_full_then_ok_sends_the_whole_sensor(self, view: DetectorView) -> None:
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
        panel = view.settings_controls["cam"].roi_panel
        assert panel is not None
        panel.select_button.click()
        view.on_roi_drawn("cam", Roi(1, 1, 3, 2))

        view.on_new_configuration("cam", "cam-roi", "1,1,3,2")

        assert panel.applied == Roi(1, 1, 3, 2)
        assert not panel.ok_button.isEnabled()


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
            view.close()

    def test_dragging_the_box_announces_a_roi_and_changes_nothing_else(
        self, view: ImageView
    ) -> None:
        drawn: list[tuple[str, Roi]] = []
        view.sig_roi_drawn.connect(lambda name, roi: drawn.append((name, roi)))

        view.viewer_model.layers["cam"]._overlays[ROI_BOX].bounds = ((1, 1), (3, 4))

        assert drawn == [("cam", Roi(1, 1, 3, 2))]

    def test_the_box_is_hidden_until_a_selection_is_asked_for(
        self, view: ImageView
    ) -> None:
        box = view.viewer_model.layers["cam"]._overlays[ROI_BOX]
        assert not box.visible

        view.set_roi_selection("cam", True)
        assert box.visible
        view.set_roi_selection("cam", False)
        assert not box.visible

    def test_the_layer_menu_finds_the_embedded_layers(self, view: ImageView) -> None:
        """The layer list's context menu asks napari's store for the layers."""
        view.viewer_model.layers.selection.active = view.viewer_model.layers["cam"]

        visible = get_app_model().injection_store.inject(_are_bounding_boxes_visible)

        assert visible() is False

    def test_a_frame_not_shaped_like_its_roi_is_dropped(self, view: ImageView) -> None:
        """A monitor first reports the frame taken before the ROI changed."""
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
        """A pixel type change must not be cast into the old layer."""
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
        drawn: list[tuple[str, Roi]] = []
        view.sig_roi_drawn.connect(lambda name, roi: drawn.append((name, roi)))

        view.set_roi_box("cam", Roi(2, 1, 3, 2))

        assert view.viewer_model.layers["cam"]._overlays[ROI_BOX].bounds == (
            (1, 2),
            (3, 5),
        )
        assert drawn == []

    def test_a_detector_layer_is_locked_against_deletion(self, view: ImageView) -> None:
        layers = view.viewer_model.layers
        layers.selection = {layers["cam"]}

        layers.remove_selected()

        assert "cam" in layers
        assert layers["cam"].locked == LayerLock.DELETION

    def test_a_derived_layer_is_plain_and_unlocked(self, view: ImageView) -> None:
        frame = np.ones((4, 6), dtype=np.float32)

        view.update_layers({"cam_median": {"value": frame, "timestamp": 0.0}})

        layer = view.viewer_model.layers["cam_median"]
        assert not layer.locked
        assert ROI_BOX not in layer._overlays
        np.testing.assert_array_equal(layer.data, frame)

    def test_a_deleted_layer_comes_back_with_its_box_and_takes_frames(
        self, view: ImageView
    ) -> None:
        """The user may bin a layer; the next run must not crash on it."""
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


class TestAcquisitionView:
    """Tests for the plan selector and its controls."""

    @pytest.fixture
    def plans(self) -> Plans:
        return Plans(DocumentRouter())

    @pytest.fixture
    def view(
        self, parent: QtWidgets.QWidget, plans: Plans, tmp_path: Path
    ) -> AcquisitionView:
        view = AcquisitionView("acq_widget", parent)
        view.setup(
            {"plans": plans},
            {"viewer": VIEWER, "median": plans.own},
            {},
            SessionPathProvider(base_dir=tmp_path),
        )
        return view

    def test_a_folder_chosen_while_idle_is_shown_once_the_provider_moves(
        self, parent: QtWidgets.QWidget, plans: Plans, tmp_path: Path
    ) -> None:
        """Show the folder the path provider moved to at the view's request."""
        paths = SessionPathProvider(base_dir=tmp_path)
        view = AcquisitionView("acq_widget", parent)
        view.setup({"plans": plans}, {}, {}, paths)
        view.sig_base_dir_request.connect(paths.set_base_dir)
        paths.sig_base_dir_changed.connect(view.on_base_dir_changed)

        view.sig_base_dir_request.emit(str(tmp_path / "elsewhere"))

        assert view.base_dir_label.text() == str(tmp_path / "elsewhere")

    def test_the_selector_is_held_on_the_plan_that_runs(
        self, view: AcquisitionView
    ) -> None:
        """Hold the selector and the root folder until the running plan is done."""
        view.plans_combobox.setCurrentText("scan")
        view.plan_widgets["scan"].run_button.setChecked(True)
        assert not view.plans_combobox.isEnabled()
        assert not view.base_dir_btn.isEnabled()
        assert view.open_dir_btn.isEnabled()

        view.plans_combobox.setCurrentText("stream")
        view.on_plan_done()

        assert view.plans_combobox.isEnabled()
        assert view.base_dir_btn.isEnabled()
        assert not view.plan_widgets["scan"].run_button.isChecked()

    def test_a_run_carries_the_callbacks_the_user_attached(
        self, view: AcquisitionView
    ) -> None:
        """Send with a plan the callbacks attached to it, not the ones it lists."""
        sent: list[tuple[str, Any, Any]] = []
        view.sig_launch_plan_request.connect(lambda *args: sent.append(args))
        view.plans_combobox.setCurrentText("scan")

        view.plan_widgets["scan"].run_button.setChecked(True)

        assert sent == [("scan", {"frames": 1}, ["viewer"])]

    def test_an_action_button_follows_the_state_of_its_action(
        self, view: AcquisitionView
    ) -> None:
        """Enable a button while offered, and release it silently once idle."""
        asked: list[tuple[str, bool]] = []
        view.sig_action_request.connect(lambda *args: asked.append(args))
        view.plans_combobox.setCurrentText("stream")
        view.plan_widgets["stream"].run_button.setChecked(True)
        buttons = view.plan_widgets["stream"].action_buttons

        view.on_action_changed("stream", "offered")
        view.on_action_changed("snap", "offered")
        assert buttons["stream"].isEnabled()
        buttons["stream"].setChecked(True)
        view.on_action_changed("stream", "running")
        view.on_action_changed("snap", "running")
        assert buttons["stream"].isEnabled()
        assert not buttons["snap"].isEnabled()
        view.on_action_changed("stream", "idle")

        assert not buttons["stream"].isEnabled()
        assert not buttons["stream"].isChecked()
        assert asked == [("stream", True)]


class TestMotorView:
    """Tests for MotorView."""

    @pytest.fixture
    def widget(self, parent: QtWidgets.QWidget) -> MotorView:
        return MotorView("motor_view", parent)

    async def test_build_creates_one_group_per_axis(
        self, widget: MotorView, motor_stage: FakeXYStage
    ) -> None:
        """Build one group per motor from the `<device>-axis-<name>` keys."""
        build_motor_view(widget, motor_stage)

        assert "xystage" in widget._groups
        for axis in ("x", "y"):
            assert f"pos:xystage:{axis}" in widget._labels
            assert f"step:xystage:{axis}" in widget._steps
            assert f"button:xystage:{axis}:up" in widget._buttons
            assert f"button:xystage:{axis}:down" in widget._buttons

    async def test_a_locked_motor_disables_its_jog_controls_and_keeps_its_readout(
        self, widget: MotorView, motor_stage: FakeXYStage
    ) -> None:
        """Disable a locked motor's jog controls and keep its readout updating."""
        build_motor_view(widget, motor_stage)

        widget.set_locked(frozenset({"xystage"}))
        widget.update_setpoint(_reading("xystage-axis-x", 7.5))

        assert not widget._buttons["button:xystage:x:up"].isEnabled()
        assert not widget._steps["step:xystage:x"].isEnabled()
        assert widget._labels["pos:xystage:x"].isEnabled()
        assert widget._labels["pos:xystage:x"].text().startswith("7.50")

        widget.set_locked(frozenset())
        assert widget._buttons["button:xystage:x:up"].isEnabled()

    async def test_step_size_comes_from_the_view(
        self, parent: QtWidgets.QWidget, motor_stage: FakeXYStage
    ) -> None:
        """Take the step size from the view, not from a device property."""
        widget = MotorView("motor_view", parent, step_size=2.5)
        build_motor_view(widget, motor_stage)

        assert widget._steps["step:xystage:x"].value() == pytest.approx(2.5)

    async def test_update_setpoint_refreshes_label(
        self, widget: MotorView, motor_stage: FakeXYStage
    ) -> None:
        """Write an axis reading into its position label."""
        build_motor_view(widget, motor_stage)

        widget.update_setpoint(_reading("xystage-axis-x", 7.5))
        assert widget._labels["pos:xystage:x"].text().startswith("7.50")

    @pytest.mark.parametrize(
        ("direction_up", "expected"),
        [
            pytest.param(True, 100.0, id="step-up"),
            pytest.param(False, -100.0, id="step-down"),
        ],
    )
    async def test_step_emits_a_displacement_not_a_target(
        self,
        widget: MotorView,
        motor_stage: FakeXYStage,
        direction_up: bool,
        expected: float,
    ) -> None:
        """Send the step size as a displacement, whatever the position label says."""
        build_motor_view(widget, motor_stage)
        widget.update_setpoint(_reading("xystage-axis-x", 123.0))

        received: list[tuple[str, str, float]] = []
        widget.sig_motor_move.connect(
            lambda motor, axis, delta: received.append((motor, axis, delta))
        )

        widget._step("xystage", "x", direction_up=direction_up)

        assert len(received) == 1
        motor, axis, delta = received[0]
        assert (motor, axis) == ("xystage", "x")
        assert delta == pytest.approx(expected)


class TestLightView:
    """Tests for LightView."""

    @pytest.fixture
    def widget(self, parent: QtWidgets.QWidget) -> LightView:
        return LightView("light_view", parent)

    async def test_build_creates_button_and_slider(
        self, widget: LightView, mock_laser: MockLightDevice
    ) -> None:
        """Build a button and a slider for a light with an intensity."""
        build_light_view(widget, mock_laser)

        assert "laser" in widget._groups
        assert "on:laser" in widget._buttons
        assert "power:laser" in widget._sliders

    async def test_only_a_locked_light_disables_its_controls(
        self, widget: LightView, mock_laser: MockLightDevice
    ) -> None:
        """Disable the controls of a locked light only."""
        build_light_view(widget, mock_laser)

        widget.set_locked(frozenset({"another_light"}))
        assert widget._buttons["on:laser"].isEnabled()

        widget.set_locked(frozenset({"laser"}))
        assert not widget._buttons["on:laser"].isEnabled()
        assert not widget._sliders["power:laser"].isEnabled()
        assert widget._groups["laser"].isEnabled()

    async def test_binary_source_gets_no_slider(
        self, widget: LightView, mock_binary_led: MockLightDevice
    ) -> None:
        """Build no slider for a binary source."""
        build_light_view(widget, mock_binary_led)

        assert "on:binary_led" in widget._buttons
        assert "power:binary_led" not in widget._sliders

    async def test_slider_range_follows_device_limits(
        self, widget: LightView, mock_laser: MockLightDevice
    ) -> None:
        """Size the slider from the device's limits."""
        build_light_view(widget, mock_laser)

        slider = widget._sliders["power:laser"]
        assert (slider.minimum(), slider.maximum()) == (0.0, 100.0)

    async def test_build_handles_multiple_devices(
        self,
        widget: LightView,
        mock_led: MockLightDevice,
        mock_laser: MockLightDevice,
    ) -> None:
        """Build one group per light."""
        build_light_view(widget, mock_led, mock_laser)

        assert {"led", "laser"} <= set(widget._groups)

    async def test_toggle_emits_and_relabels(
        self, widget: LightView, mock_led: MockLightDevice
    ) -> None:
        """Ask for a toggle and relabel the button."""
        build_light_view(widget, mock_led)

        received: list[str] = []
        widget.sig_toggle_light_request.connect(received.append)
        button = widget._buttons["on:led"]

        assert button.text() == "ON"
        button.setChecked(True)
        widget._on_toggle_button_checked("led")
        assert button.text() == "OFF"
        button.setChecked(False)
        widget._on_toggle_button_checked("led")
        assert button.text() == "ON"

        assert received == ["led", "led"]

    async def test_slider_change_emits_intensity_request(
        self, widget: LightView, mock_laser: MockLightDevice
    ) -> None:
        """Ask for the intensity a slider is moved to."""
        build_light_view(widget, mock_laser)

        received: list[tuple[str, Any]] = []
        widget.sig_intensity_request.connect(
            lambda name, value: received.append((name, value))
        )

        widget._on_slider_changed(50, "laser")

        assert received == [("laser", 50)]

    async def test_non_numeric_intensity_is_rejected(
        self, widget: LightView, mock_led: MockLightDevice
    ) -> None:
        """Raise `TypeError` for an intensity that is not a number."""
        readings: dict[str, Any] = {
            **await mock_led.read_configuration(),
            **await mock_led.read(),
        }
        description: dict[str, Any] = {
            **await mock_led.describe_configuration(),
            **await mock_led.describe(),
        }
        description["led-intensity"] = {
            **description["led-intensity"],
            "dtype": "string",
        }

        with pytest.raises(TypeError, match="'number' or 'integer'"):
            widget.setup_ui(readings, description)


@needs_opengl
class TestImageViewTheme:
    """Tests for styling the embedded napari viewer."""

    def test_it_carries_no_stylesheet_of_its_own(
        self, parent: QtWidgets.QWidget
    ) -> None:
        """Carry no stylesheet, so the application's one styles the view."""
        get_settings().appearance.theme = "dark"

        view = ImageView("image_view", parent)

        try:
            assert view.styleSheet() == ""
            assert view._qt_viewer.styleSheet() == ""
            # the canvas and the layer controls read the theme off the model,
            # which takes it from the same settings the stylesheet does
            assert view.viewer_model.theme == "dark"
        finally:
            view.close()


class TestNapariApplication:
    """Tests for the hook that runs the session on napari's application."""

    @pytest.fixture
    def hook(self) -> NapariApplication:
        get_settings().appearance.theme = "dark"
        return NapariApplication()

    def test_it_supplies_naparis_application(
        self, hook: NapariApplication, qapp: QCoreApplication
    ) -> None:
        assert hook.create_application([]) is qapp

    def test_it_styles_the_whole_application(
        self, hook: NapariApplication, qapp: QCoreApplication
    ) -> None:
        app = cast("QApplication", qapp)
        # restyling repolishes every live widget, so drop the ones earlier
        # tests closed but the interpreter has not collected yet
        gc.collect()
        app.processEvents()

        hook.configure_application(app)

        assert app.styleSheet() == stylesheet(FONT_SIZE)
        assert f"font-size: {FONT_SIZE}pt" in app.styleSheet()
