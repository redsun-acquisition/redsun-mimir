"""Tests for Qt view widgets."""

from __future__ import annotations

import os
import sys
from typing import Any

import pytest
from dependency_injector import providers
from qtpy.QtWidgets import QApplication
from redsun.virtual import VirtualContainer

from redsun_mimir.device._mocks import MockLightDevice, MockMotorDevice
from redsun_mimir.view._light import LightView
from redsun_mimir.view._motor import MotorView


def _make_container(**objects: Any) -> VirtualContainer:
    container = VirtualContainer()
    for name, value in objects.items():
        setattr(container, name, providers.Object(value))
    return container


def _build_motor_view(widget: MotorView, motor: MockMotorDevice, container: VirtualContainer | None = None) -> VirtualContainer:
    """Full build sequence: register_providers then inject_dependencies."""
    if container is None:
        container = _make_container(
            motor_configuration=motor.read_configuration(),
            motor_description=motor.describe_configuration(),
        )
    widget.register_providers(container)
    widget.inject_dependencies(container)
    return container


def _build_light_view(widget: LightView, *devices: MockLightDevice, container: VirtualContainer | None = None) -> VirtualContainer:
    """Full build sequence: register_providers then inject_dependencies."""
    if container is None:
        cfg: dict[str, Any] = {}
        desc: dict[str, Any] = {}
        for dev in devices:
            cfg.update(dev.read_configuration())
            desc.update(dev.describe_configuration())
        container = _make_container(
            light_configuration=cfg,
            light_description=desc,
        )
    widget.register_providers(container)
    widget.inject_dependencies(container)
    return container


@pytest.mark.skipif(
    sys.platform == "linux" and not os.environ.get("DISPLAY"),
    reason="requires a display (Qt) on Linux",
)
class TestMotorView:
    """Tests for MotorView."""

    @pytest.fixture
    def motor(self) -> MockMotorDevice:
        return MockMotorDevice(
            "stage", axis=["X", "Y"], step_sizes={"X": 1.0, "Y": 0.5}, egu="um"
        )

    @pytest.fixture
    def widget(
        self, qapp: QApplication, virtual_container: VirtualContainer
    ) -> MotorView:
        return MotorView("motor_view")

    def test_instantiation(self, widget: MotorView) -> None:
        """Widget creates without error before inject_dependencies."""
        assert widget is not None

    def test_register_providers_builds_ui(
        self, widget: MotorView, motor: MockMotorDevice
    ) -> None:
        """register_providers() + inject_dependencies() populates group boxes, labels, and buttons."""
        _build_motor_view(widget, motor)

        assert "stage" in widget._groups
        assert "pos:stage:X" in widget._labels
        assert "pos:stage:Y" in widget._labels
        assert "button:stage:X:up" in widget._buttons
        assert "button:stage:X:down" in widget._buttons

    def test_step_size_initialised_from_device(
        self, widget: MotorView, motor: MockMotorDevice
    ) -> None:
        """Step size line edits are seeded from device step_sizes."""
        _build_motor_view(widget, motor)

        assert widget._line_edits["edit:stage:X"].text() == "1.0"
        assert widget._line_edits["edit:stage:Y"].text() == "0.5"

    def test_update_position_changes_label(
        self, widget: MotorView, motor: MockMotorDevice
    ) -> None:
        """_update_position() refreshes the position label text."""
        _build_motor_view(widget, motor)

        widget._update_position("stage", "X", 7.5)
        assert "7.50" in widget._labels["pos:stage:X"].text()

    def test_step_up_emits_signal(
        self, widget: MotorView, motor: MockMotorDevice
    ) -> None:
        """Clicking the '+' button emits sigMotorMove with position + step."""
        _build_motor_view(widget, motor)

        received: list[tuple[str, str, float]] = []
        widget.sigMotorMove.connect(lambda m, a, p: received.append((m, a, p)))

        widget._step("stage", "X", direction_up=True)
        assert len(received) == 1
        assert received[0] == ("stage", "X", pytest.approx(1.0))

    def test_step_down_emits_signal(
        self, widget: MotorView, motor: MockMotorDevice
    ) -> None:
        """Clicking the '-' button emits sigMotorMove with position - step."""
        _build_motor_view(widget, motor)

        received: list[tuple[str, str, float]] = []
        widget.sigMotorMove.connect(lambda m, a, p: received.append((m, a, p)))

        widget._step("stage", "X", direction_up=False)
        assert len(received) == 1
        assert received[0] == ("stage", "X", pytest.approx(-1.0))

    def test_inject_dependencies_registers_signals(
        self,
        widget: MotorView,
        motor: MockMotorDevice,
        virtual_container: VirtualContainer,
    ) -> None:
        """register_providers() registers the widget signals; inject_dependencies() connects inbound signals."""
        from redsun_mimir.presenter._motor import MotorPresenter

        # Presenter registers first so its signals and providers exist on the container
        ctrl = MotorPresenter("motor_presenter", {"stage": motor})
        ctrl.register_providers(virtual_container)

        # View register_providers then inject_dependencies in the correct build order
        widget.register_providers(virtual_container)
        widget.inject_dependencies(virtual_container)
        ctrl.shutdown()

        assert "motor_view" in virtual_container.signals


@pytest.mark.skipif(
    sys.platform == "linux" and not os.environ.get("DISPLAY"),
    reason="requires a display (Qt) on Linux",
)
class TestLightView:
    """Tests for LightView."""

    @pytest.fixture
    def led(self) -> MockLightDevice:
        return MockLightDevice(
            "led", wavelength=450, binary=True, intensity_range=(0, 0)
        )

    @pytest.fixture
    def laser(self) -> MockLightDevice:
        return MockLightDevice(
            "laser", wavelength=650, egu="mW", intensity_range=(0, 100), step_size=1
        )

    @pytest.fixture
    def widget(
        self, qapp: QApplication, virtual_container: VirtualContainer
    ) -> LightView:
        return LightView("light_view")

    def test_instantiation(self, widget: LightView) -> None:
        """Widget creates without error before inject_dependencies."""
        assert widget is not None

    def test_inject_binary_light(self, widget: LightView, led: MockLightDevice) -> None:
        """register_providers() + inject_dependencies() with binary device creates only an ON/OFF button."""
        _build_light_view(widget, led)

        assert "led" in widget._groups
        assert "on:led" in widget._buttons
        assert "power:led" not in widget._sliders

    def test_inject_continuous_light(
        self, widget: LightView, laser: MockLightDevice
    ) -> None:
        """register_providers() + inject_dependencies() with continuous device creates a button and slider."""
        _build_light_view(widget, laser)

        assert "laser" in widget._groups
        assert "on:laser" in widget._buttons
        assert "power:laser" in widget._sliders

    def test_toggle_button_emits_signal(
        self, widget: LightView, led: MockLightDevice
    ) -> None:
        """Clicking the ON button emits sigToggleLightRequest with the device name."""
        _build_light_view(widget, led)

        received: list[str] = []
        widget.sigToggleLightRequest.connect(received.append)

        widget._on_toggle_button_checked("led")
        assert received == ["led"]

    def test_toggle_button_text_changes(
        self, widget: LightView, led: MockLightDevice
    ) -> None:
        """Toggle button label switches between ON and OFF."""
        _build_light_view(widget, led)

        btn = widget._buttons["on:led"]
        assert btn.text() == "ON"
        btn.setChecked(True)
        widget._on_toggle_button_checked("led")
        assert btn.text() == "OFF"
        btn.setChecked(False)
        widget._on_toggle_button_checked("led")
        assert btn.text() == "ON"

    def test_slider_change_emits_signal(
        self, widget: LightView, laser: MockLightDevice
    ) -> None:
        """Moving the intensity slider emits sigIntensityRequest."""
        _build_light_view(widget, laser)

        received: list[tuple[str, Any]] = []
        widget.sigIntensityRequest.connect(lambda n, v: received.append((n, v)))

        widget._on_slider_changed(50, "laser")
        assert len(received) == 1
        assert received[0][0] == "laser"
        assert received[0][1] == 50

    def test_inject_dependencies_registers_signals(
        self,
        widget: LightView,
        led: MockLightDevice,
        virtual_container: VirtualContainer,
    ) -> None:
        """register_providers() registers the widget signals; inject_dependencies() builds the UI."""
        from redsun_mimir.presenter._light import LightPresenter

        ctrl = LightPresenter("light_presenter", {"led": led})
        ctrl.register_providers(virtual_container)

        # View register_providers then inject_dependencies in the correct build order
        widget.register_providers(virtual_container)
        widget.inject_dependencies(virtual_container)

        assert "light_view" in virtual_container.signals
