"""Tests for Qt view widgets."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import numpy as np
import pytest
from bluesky.utils import MsgGenerator
from napari.settings import get_settings
from redsun.engine.actions import continous
from redsun.path_provider import PATH_PROVIDER, SessionPathProvider
from redsun.presenter.plan_spec import create_plan_spec
from redsun.virtual import ProviderKey, VirtualContainer

from redsun_mimir.common import Roi
from redsun_mimir.hooks import FONT_SIZE, NapariApplication
from redsun_mimir.presenter.light import LightPresenter
from redsun_mimir.presenter.motor import MotorPresenter
from redsun_mimir.providers import (
    LIGHT_CONFIGURATION,
    LIGHT_DESCRIPTION,
    MOTOR_DESCRIPTION,
    MOTOR_READBACKS,
    MOTOR_READINGS,
    PLAN_SPECS,
)
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

    from redsun_mimir.device._mocks import MockLightDevice

    from .conftest import FakeDetector, FakeXYStage

pytestmark = pytest.mark.qt


def _reading(key: str, value: float) -> dict[str, Reading[Any]]:
    """Build the one-entry reading dict a signal subscription delivers."""
    return {key: {"value": value, "timestamp": 0.0}}


def _make_container(*bindings: tuple[ProviderKey[Any], Any]) -> VirtualContainer:
    container = VirtualContainer()
    for key, value in bindings:
        container.provide(key, value)
    return container


async def _build_motor_view(widget: MotorView, motor: FakeXYStage) -> VirtualContainer:
    """Drive the real build order: register_providers then inject_dependencies."""
    container = _make_container(
        (MOTOR_READINGS, await motor.read()),
        (MOTOR_DESCRIPTION, await motor.describe()),
        (
            MOTOR_READBACKS,
            {a.name: a.movable_logic.readback for a in motor.axis.values()},
        ),
    )
    widget.register_providers(container)
    widget.inject_dependencies(container)
    return container


async def _build_light_view(
    widget: LightView, *devices: MockLightDevice
) -> VirtualContainer:
    """Drive the real build order: register_providers then inject_dependencies."""
    # mirrors LightPresenter.device_configuration/_description: the view needs
    # both the config signals (wavelength) and the readables (intensity)
    configuration: dict[str, Any] = {}
    description: dict[str, Any] = {}
    for device in devices:
        configuration.update(await device.read_configuration())
        configuration.update(await device.read())
        description.update(await device.describe_configuration())
        description.update(await device.describe())
    container = _make_container(
        (LIGHT_CONFIGURATION, configuration),
        (LIGHT_DESCRIPTION, description),
    )
    widget.register_providers(container)
    widget.inject_dependencies(container)
    return container


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
        self, qapp: QApplication, fake_detector: FakeDetector
    ) -> DetectorView:
        view = DetectorView("det_widget")
        view.setup_ui(
            await fake_detector.describe_configuration(),
            await fake_detector.read_configuration(),
        )
        return view

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
    def view(self, qapp: QCoreApplication) -> Iterator[ImageView]:
        view = ImageView("image_view")
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
    def view(self, qapp: QApplication, tmp_path: Path) -> AcquisitionView:
        @continous(togglable=True)
        def stream(frames: int = 1) -> MsgGenerator[None]:
            yield from ()

        def scan(frames: int = 1) -> MsgGenerator[None]:
            yield from ()

        view = AcquisitionView("acq_widget")
        view.inject_dependencies(
            _make_container(
                (PATH_PROVIDER, SessionPathProvider(base_dir=tmp_path)),
                (
                    PLAN_SPECS,
                    {create_plan_spec(stream, {}), create_plan_spec(scan, {})},
                ),
            )
        )
        return view

    def test_the_selector_is_held_on_the_plan_that_runs(
        self, view: AcquisitionView
    ) -> None:
        """Switching plans mid-run would re-enable the wrong page."""
        view.plans_combobox.setCurrentText("scan")
        view.plan_widgets["scan"].run_button.click()
        assert not view.plans_combobox.isEnabled()
        assert not view.plan_widgets["scan"].group_box.isEnabled()

        view.plans_combobox.setCurrentText("stream")
        view.on_plan_done()

        assert view.plans_combobox.isEnabled()
        assert view.plan_widgets["scan"].group_box.isEnabled()

    def test_a_stream_holds_the_selector_until_it_is_done(
        self, view: AcquisitionView
    ) -> None:
        view.plans_combobox.setCurrentText("stream")
        view.plan_widgets["stream"].run_button.setChecked(True)
        assert not view.plans_combobox.isEnabled()

        view.plan_widgets["stream"].run_button.setChecked(False)
        view.on_plan_done()

        assert view.plans_combobox.isEnabled()


class TestMotorView:
    """Tests for MotorView."""

    @pytest.fixture
    def widget(self) -> MotorView:
        return MotorView("motor_view")

    async def test_build_creates_one_group_per_axis(
        self, widget: MotorView, motor_stage: FakeXYStage
    ) -> None:
        """The UI is derived from the ``<device>-axis-<name>`` reading keys."""
        await _build_motor_view(widget, motor_stage)

        assert "xystage" in widget._groups
        for axis in ("x", "y"):
            assert f"pos:xystage:{axis}" in widget._labels
            assert f"button:xystage:{axis}:up" in widget._buttons
            assert f"button:xystage:{axis}:down" in widget._buttons

    async def test_step_size_comes_from_the_view(
        self, widget: MotorView, motor_stage: FakeXYStage
    ) -> None:
        """Step size is the view's own parameter, not a device property."""
        widget = MotorView("motor_view", step_size=2.5)
        await _build_motor_view(widget, motor_stage)

        assert widget._line_edits["edit:xystage:x"].text() == "2.5"

    async def test_update_setpoint_refreshes_label(
        self, widget: MotorView, motor_stage: FakeXYStage
    ) -> None:
        await _build_motor_view(widget, motor_stage)

        widget.update_setpoint(_reading("xystage-axis-x", 7.5))
        assert widget._labels["pos:xystage:x"].text().startswith("7.50")

    @pytest.mark.parametrize(
        ("direction_up", "expected"),
        [
            pytest.param(True, 10.0, id="step-up"),
            pytest.param(False, -10.0, id="step-down"),
        ],
    )
    async def test_step_emits_a_displacement_not_a_target(
        self,
        widget: MotorView,
        motor_stage: FakeXYStage,
        direction_up: bool,
        expected: float,
    ) -> None:
        """The step size travels as-is, whatever the position label says.

        The label is not read at all: if it were, two clicks arriving before it
        refreshed would both compute the same absolute target and the second
        would move nothing.
        """
        await _build_motor_view(widget, motor_stage)
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

    async def test_label_follows_a_move_the_presenter_never_made(
        self,
        widget: MotorView,
        motor_stage: FakeXYStage,
        virtual_container: VirtualContainer,
    ) -> None:
        """The label reports the axis, not the last request the view sent.

        The axis is moved directly, exactly as a plan running in the
        `RunEngine` would move it: nothing passes through the presenter, and
        the label still tracks it.
        """
        presenter = MotorPresenter("motor_ctrl", {"xystage": motor_stage})
        presenter.register_providers(virtual_container)
        widget.register_providers(virtual_container)
        widget.inject_dependencies(virtual_container)

        assert "motor_view" in virtual_container.signals

        await motor_stage.axis["x"].set(3.25)
        assert widget._labels["pos:xystage:x"].text().startswith("3.25")

        presenter.shutdown()


class TestLightView:
    """Tests for LightView."""

    @pytest.fixture
    def widget(self) -> LightView:
        return LightView("light_view")

    async def test_build_creates_button_and_slider(
        self, widget: LightView, mock_laser: MockLightDevice
    ) -> None:
        await _build_light_view(widget, mock_laser)

        assert "laser" in widget._groups
        assert "on:laser" in widget._buttons
        assert "power:laser" in widget._sliders

    async def test_binary_source_gets_no_slider(
        self, widget: LightView, mock_binary_led: MockLightDevice
    ) -> None:
        """A binary source offers on/off and nothing else."""
        await _build_light_view(widget, mock_binary_led)

        assert "on:binary_led" in widget._buttons
        assert "power:binary_led" not in widget._sliders

    async def test_slider_range_follows_device_limits(
        self, widget: LightView, mock_laser: MockLightDevice
    ) -> None:
        await _build_light_view(widget, mock_laser)

        slider = widget._sliders["power:laser"]
        assert (slider.minimum(), slider.maximum()) == (0.0, 100.0)

    async def test_build_handles_multiple_devices(
        self,
        widget: LightView,
        mock_led: MockLightDevice,
        mock_laser: MockLightDevice,
    ) -> None:
        await _build_light_view(widget, mock_led, mock_laser)

        assert {"led", "laser"} <= set(widget._groups)

    async def test_toggle_emits_and_relabels(
        self, widget: LightView, mock_led: MockLightDevice
    ) -> None:
        await _build_light_view(widget, mock_led)

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
        await _build_light_view(widget, mock_laser)

        received: list[tuple[str, Any]] = []
        widget.sig_intensity_request.connect(
            lambda name, value: received.append((name, value))
        )

        widget._on_slider_changed(50, "laser")

        assert received == [("laser", 50)]

    async def test_non_numeric_intensity_is_rejected(
        self, widget: LightView, mock_led: MockLightDevice
    ) -> None:
        """The view has no binary branch: a non-numeric dtype must raise."""
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

    async def test_registers_signals_on_the_container(
        self,
        widget: LightView,
        mock_led: MockLightDevice,
        virtual_container: VirtualContainer,
    ) -> None:
        presenter = LightPresenter("light_ctrl", {"led": mock_led})
        presenter.register_providers(virtual_container)
        widget.register_providers(virtual_container)
        widget.inject_dependencies(virtual_container)

        assert "light_view" in virtual_container.signals


@needs_opengl
class TestImageViewTheme:
    """Tests for styling the embedded napari viewer."""

    def test_it_carries_no_stylesheet_of_its_own(self, qapp: QCoreApplication) -> None:
        """The view is styled by the application, never by itself.

        A stylesheet set on the widget would win over the application's and
        pin the view to the theme it was built under.
        """
        get_settings().appearance.theme = "dark"
        NapariApplication().configure_application(cast("QApplication", qapp))

        view = ImageView("image_view")

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

        hook.configure_application(app)

        assert app.styleSheet() == stylesheet(FONT_SIZE)
        assert f"font-size: {FONT_SIZE}pt" in app.styleSheet()
