"""Tests for Qt view widgets."""

from __future__ import annotations

import sys
from typing import Any

import pytest
from dependency_injector import providers
from dependency_injector.containers import DynamicContainer
from qtpy.QtWidgets import QApplication
from sunflare.virtual import VirtualBus

from redsun_mimir.device._mocks import MockLightDevice, MockMotorDevice
from redsun_mimir.view._light import LightWidget
from redsun_mimir.view._motor import MotorWidget

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    """Session-scoped QApplication (offscreen)."""
    return QApplication.instance() or QApplication(sys.argv)


def _make_container(**objects: Any) -> DynamicContainer:
    container = DynamicContainer()
    for name, value in objects.items():
        setattr(container, name, providers.Object(value))
    return container


# ---------------------------------------------------------------------------
# MotorWidget
# ---------------------------------------------------------------------------


class TestMotorWidget:
    """Tests for MotorWidget."""

    @pytest.fixture
    def motor(self) -> MockMotorDevice:
        return MockMotorDevice(
            "stage", axis=["X", "Y"], step_sizes={"X": 1.0, "Y": 0.5}, egu="um"
        )

    @pytest.fixture
    def widget(self, qapp: QApplication, virtual_bus: VirtualBus) -> MotorWidget:
        return MotorWidget(virtual_bus)

    def test_instantiation(self, widget: MotorWidget) -> None:
        """Widget creates without error before inject_dependencies."""
        assert widget is not None

    def test_inject_dependencies_builds_ui(
        self, widget: MotorWidget, motor: MockMotorDevice
    ) -> None:
        """inject_dependencies() populates group boxes, labels, and buttons."""
        container = _make_container(motor_models={"stage": motor})
        widget.inject_dependencies(container)

        assert "stage" in widget._groups
        assert "pos:stage:X" in widget._labels
        assert "pos:stage:Y" in widget._labels
        assert "button:stage:X:up" in widget._buttons
        assert "button:stage:X:down" in widget._buttons

    def test_step_size_initialised_from_device(
        self, widget: MotorWidget, motor: MockMotorDevice
    ) -> None:
        """Step size line edits are seeded from device step_sizes."""
        container = _make_container(motor_models={"stage": motor})
        widget.inject_dependencies(container)

        assert widget._line_edits["edit:stage:X"].text() == "1.0"
        assert widget._line_edits["edit:stage:Y"].text() == "0.5"

    def test_update_position_changes_label(
        self, widget: MotorWidget, motor: MockMotorDevice
    ) -> None:
        """_update_position() refreshes the position label text."""
        container = _make_container(motor_models={"stage": motor})
        widget.inject_dependencies(container)

        widget._update_position("stage", "X", 7.5)
        assert "7.50" in widget._labels["pos:stage:X"].text()

    def test_step_up_emits_signal(
        self, widget: MotorWidget, motor: MockMotorDevice
    ) -> None:
        """Clicking the '+' button emits sigMotorMove with position + step."""
        container = _make_container(motor_models={"stage": motor})
        widget.inject_dependencies(container)

        received: list[tuple[str, str, float]] = []
        widget.sigMotorMove.connect(lambda m, a, p: received.append((m, a, p)))

        widget._step("stage", "X", direction_up=True)
        assert len(received) == 1
        assert received[0] == ("stage", "X", pytest.approx(1.0))

    def test_step_down_emits_signal(
        self, widget: MotorWidget, motor: MockMotorDevice
    ) -> None:
        """Clicking the '-' button emits sigMotorMove with position - step."""
        container = _make_container(motor_models={"stage": motor})
        widget.inject_dependencies(container)

        received: list[tuple[str, str, float]] = []
        widget.sigMotorMove.connect(lambda m, a, p: received.append((m, a, p)))

        widget._step("stage", "X", direction_up=False)
        assert len(received) == 1
        assert received[0] == ("stage", "X", pytest.approx(-1.0))

    def test_connect_to_virtual_registers_signals(
        self, widget: MotorWidget, motor: MockMotorDevice, virtual_bus: VirtualBus
    ) -> None:
        """connect_to_virtual() registers the widget's signals on the bus."""
        from redsun_mimir.presenter._motor import MotorController

        container = _make_container(motor_models={"stage": motor})
        widget.inject_dependencies(container)

        # The presenter must be registered first so its signals exist on the bus
        ctrl = MotorController({"stage": motor}, virtual_bus)
        ctrl.register_providers(container)

        widget.connect_to_virtual()

        assert "MotorWidget" in virtual_bus.signals
        ctrl.shutdown()


# ---------------------------------------------------------------------------
# LightWidget
# ---------------------------------------------------------------------------


class TestLightWidget:
    """Tests for LightWidget."""

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
    def widget(self, qapp: QApplication, virtual_bus: VirtualBus) -> LightWidget:
        return LightWidget(virtual_bus)

    def test_instantiation(self, widget: LightWidget) -> None:
        """Widget creates without error before inject_dependencies."""
        assert widget is not None

    def test_inject_binary_light(
        self, widget: LightWidget, led: MockLightDevice
    ) -> None:
        """Binary device gets only an ON/OFF button, no slider."""
        container = _make_container(light_models={"led": led})
        widget.inject_dependencies(container)

        assert "led" in widget._groups
        assert "on:led" in widget._buttons
        assert "power:led" not in widget._sliders

    def test_inject_continuous_light(
        self, widget: LightWidget, laser: MockLightDevice
    ) -> None:
        """Continuous device gets both a button and an intensity slider."""
        container = _make_container(light_models={"laser": laser})
        widget.inject_dependencies(container)

        assert "laser" in widget._groups
        assert "on:laser" in widget._buttons
        assert "power:laser" in widget._sliders

    def test_toggle_button_emits_signal(
        self, widget: LightWidget, led: MockLightDevice
    ) -> None:
        """Clicking the ON button emits sigToggleLightRequest with the device name."""
        container = _make_container(light_models={"led": led})
        widget.inject_dependencies(container)

        received: list[str] = []
        widget.sigToggleLightRequest.connect(received.append)

        widget._on_toggle_button_checked("led")
        assert received == ["led"]

    def test_toggle_button_text_changes(
        self, widget: LightWidget, led: MockLightDevice
    ) -> None:
        """Toggle button label switches between ON and OFF."""
        container = _make_container(light_models={"led": led})
        widget.inject_dependencies(container)

        btn = widget._buttons["on:led"]
        assert btn.text() == "ON"
        btn.setChecked(True)
        widget._on_toggle_button_checked("led")
        assert btn.text() == "OFF"
        btn.setChecked(False)
        widget._on_toggle_button_checked("led")
        assert btn.text() == "ON"

    def test_slider_change_emits_signal(
        self, widget: LightWidget, laser: MockLightDevice
    ) -> None:
        """Moving the intensity slider emits sigIntensityRequest."""
        container = _make_container(light_models={"laser": laser})
        widget.inject_dependencies(container)

        received: list[tuple[str, Any]] = []
        widget.sigIntensityRequest.connect(lambda n, v: received.append((n, v)))

        widget._on_slider_changed(50, "laser")
        assert len(received) == 1
        assert received[0][0] == "laser"
        assert received[0][1] == 50

    def test_connect_to_virtual_registers_signals(
        self, widget: LightWidget, led: MockLightDevice, virtual_bus: VirtualBus
    ) -> None:
        """connect_to_virtual() registers the widget's signals on the bus."""
        container = _make_container(light_models={"led": led})
        widget.inject_dependencies(container)
        widget.connect_to_virtual()

        assert "LightWidget" in virtual_bus.signals
