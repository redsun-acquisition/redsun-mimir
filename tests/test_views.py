"""Tests for Qt view widgets."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest
from napari.settings import get_settings
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
)
from redsun_mimir.utils.napari import stylesheet
from redsun_mimir.view.image import ImageView
from redsun_mimir.view.light import LightView
from redsun_mimir.view.motor import MotorView

from .conftest import needs_opengl

if TYPE_CHECKING:
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

    def test_it_is_themed_as_it_is_built(self) -> None:
        get_settings().appearance.theme = "dark"

        view = ImageView("image_view")

        try:
            assert view.styleSheet() != ""
            assert view.styleSheet() == view._qt_viewer.styleSheet()
            # the canvas and the layer controls read the theme off the model,
            # not off the stylesheet
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
