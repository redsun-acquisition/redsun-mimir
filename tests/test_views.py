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

from redsun_mimir.hooks import NapariApplication
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
from redsun_mimir.roi import Roi
from redsun_mimir.utils.napari import stylesheet
from redsun_mimir.view.acquisition import AcquisitionView
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

    from .conftest import FakeXYStage

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

    def test_the_box_follows_the_roi_the_camera_reads(self, view: ImageView) -> None:
        drawn: list[tuple[str, Roi]] = []
        view.sig_roi_drawn.connect(lambda name, roi: drawn.append((name, roi)))

        view.on_new_configuration("cam", "exposure", 5.0)
        view.on_new_configuration("cam", "roi", "2,1,3,2")

        box = view.viewer_model.layers["cam"]._overlays[ROI_BOX]
        assert box.bounds == ((1, 2), (3, 5))
        assert drawn == []


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

        assert app.styleSheet() == stylesheet()

    def test_a_font_size_it_is_given_reaches_the_application(
        self, qapp: QCoreApplication
    ) -> None:
        """Every widget of a session is styled by this sheet, not just the viewer.

        napari's own size is larger than what a platform gives a Qt
        application, so a session may ask for its own.
        """
        app = cast("QApplication", qapp)

        NapariApplication(font_size=9).configure_application(app)

        assert "font-size: 9pt" in app.styleSheet()
        assert app.styleSheet() == stylesheet(9)
        assert app.styleSheet() != stylesheet()
