"""Smoke tests for the shipped example sessions.

Building one exercises the whole declaration path: every device, presenter
and view class resolves, the YAML session files match the declarations, and
the build steps run to completion. `run()` is never called: it enters the Qt
event loop and never returns.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from redsun import Layer, satisfying

from redsun_mimir.configurations import (
    build_simulation_container,
    build_uc2_container,
)
from redsun_mimir.protocols import (
    DetectorProtocol,
    HasBuffer,
    MotorProtocol,
)

from .conftest import HAS_OPENGL, NO_OPENGL_REASON

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from redsun_mimir.configurations._base import MimirApp

pytestmark = pytest.mark.qt


#: Declared by `MimirApp`, so every session has them whatever its hardware.
SHARED_PRESENTERS = {
    "median_ctrl",
    "det_ctrl",
    "acq_ctrl",
    "light_ctrl",
    "motor_ctrl",
}
SHARED_VIEWS = {
    "acq_widget",
    "img_widget",
    "det_widget",
    "light_widget",
    "motor_widget",
    "logs",
}

SIMULATION_DEVICES = {"mmcamera", "XY", "Z", "laser", "led"}

#: Every link the simulation session makes, as `(publisher.port, consumer.port)`.
SIMULATION_LINKS = {
    ("det_ctrl.sig_new_data", "img_widget.update_layers"),
    ("det_widget.sig_property_changed", "det_ctrl.set"),
    ("det_ctrl.sig_new_configuration", "det_widget.on_new_configuration"),
    ("det_ctrl.sig_new_configuration", "img_widget.on_new_configuration"),
    ("img_widget.sig_roi_drawn", "det_widget.on_roi_drawn"),
    ("det_widget.sig_roi_selection", "img_widget.set_roi_selection"),
    ("det_widget.sig_roi_edited", "img_widget.set_roi_box"),
    ("median_ctrl.median", "img_widget.update_layers"),
    ("median_ctrl.filtered", "img_widget.update_layers"),
    ("motor_widget.sig_move", "motor_ctrl.move"),
    ("motor_widget.sig_move_to", "motor_ctrl.move_to"),
    ("motor_widget.sig_stop_device", "motor_ctrl.stop"),
    ("motor_widget.sig_configure", "motor_ctrl.configure"),
    ("motor_ctrl.sig_readback", "motor_widget.update_readback"),
    ("motor_ctrl.sig_moving", "motor_widget.set_moving"),
    ("motor_ctrl.sig_failed", "motor_widget.set_failed"),
    ("motor_ctrl.sig_limits", "motor_widget.update_limits"),
    ("motor_ctrl.sig_configuration", "motor_widget.update_configuration"),
    ("light_widget.sig_enabled", "light_ctrl.set_enabled"),
    ("light_widget.sig_intensity", "light_ctrl.set_intensity"),
    ("light_widget.sig_configure", "light_ctrl.configure"),
    ("light_ctrl.sig_enabled", "light_widget.update_enabled"),
    ("light_ctrl.sig_intensity", "light_widget.update_intensity"),
    ("light_ctrl.sig_failed", "light_widget.set_failed"),
    ("light_ctrl.sig_configuration", "light_widget.update_configuration"),
    ("acq_widget.sig_launch", "acq_ctrl.launch"),
    ("acq_widget.sig_pause", "acq_ctrl.pause"),
    ("acq_widget.sig_resume", "acq_ctrl.resume"),
    ("acq_widget.sig_stop", "acq_ctrl.stop"),
    ("acq_widget.sig_action", "acq_ctrl.request_action"),
    ("acq_widget.sig_base_dir", "acq_ctrl.set_base_dir"),
    ("acq_widget.sig_label", "acq_ctrl.set_label"),
    ("acq_ctrl.sig_plan_started", "acq_widget.set_started"),
    ("acq_ctrl.sig_plan_done", "acq_widget.set_done"),
    ("acq_ctrl.sig_plan_stopped", "acq_widget.set_stopped"),
    ("acq_ctrl.sig_plan_failed", "acq_widget.set_failed"),
    ("acq_ctrl.sig_progress", "acq_widget.update_progress"),
    ("acq_ctrl.sig_action_changed", "acq_widget.update_action"),
    ("acq_ctrl.sig_base_dir_changed", "acq_widget.update_base_dir"),
    ("acq_ctrl.sig_plan_started", "median_ctrl.clear_medians"),
    ("acq_ctrl.sig_locks_changed", "det_widget.set_locked"),
    ("acq_ctrl.sig_locks_changed", "motor_widget.set_locked"),
    ("acq_ctrl.sig_locks_changed", "motor_ctrl.set_locked"),
    ("acq_ctrl.sig_locks_changed", "light_ctrl.set_locked"),
    ("acq_ctrl.sig_locks_changed", "light_widget.set_locked"),
}


@pytest.fixture(scope="module")
def simulation() -> Iterator[MimirApp]:
    """Return the built simulation session, shut down after the module.

    Building it needs a real OpenGL context for the napari viewer, so a test
    taking it is skipped headless. A mark cannot do that from a fixture.
    """
    if not HAS_OPENGL:
        pytest.skip(NO_OPENGL_REASON)
    session = build_simulation_container()
    try:
        session.build()
        yield session
    finally:
        session.shutdown()


@pytest.mark.parametrize(
    ("factory", "session_name", "devices"),
    [
        pytest.param(
            build_simulation_container,
            "mimir-sim",
            SIMULATION_DEVICES,
            id="simulation",
        ),
        pytest.param(
            build_uc2_container, "mimir-uc2", {"iscat", "stage", "laser"}, id="uc2"
        ),
    ],
)
def test_a_session_declares_only_its_devices(
    factory: Callable[[], MimirApp], session_name: str, devices: set[str]
) -> None:
    """Read each session's files, which differ from the other's only in devices."""
    session = factory()
    try:
        session.read_configuration()

        layers = {
            layer: {n for n, d in session.declarations.items() if d.kind is layer}
            for layer in Layer
        }
        assert session.name == session_name
        assert layers[Layer.DEVICE] == devices
        assert layers[Layer.PRESENTER] == SHARED_PRESENTERS
        assert layers[Layer.VIEW] == SHARED_VIEWS
        installed = {
            point: [type(provider).__name__ for provider in providers]
            for point, providers in session.hooks.items()
            if providers
        }
        assert installed == {
            "create_application": ["NapariApplication"],
            "configure_application": ["NapariStyle"],
        }
    finally:
        session.shutdown()


def test_the_simulation_builds_every_component(simulation: MimirApp) -> None:
    """Build every device, presenter and view the simulation declares."""
    assert set(simulation.devices) == SIMULATION_DEVICES
    assert set(simulation.presenters) == SHARED_PRESENTERS
    assert set(simulation.views) == SHARED_VIEWS


@pytest.mark.parametrize(
    ("protocol", "devices"),
    [
        (DetectorProtocol, {"mmcamera"}),
        (HasBuffer, {"mmcamera"}),
        (MotorProtocol, {"XY", "Z"}),
    ],
    ids=["detectors", "buffers", "motors"],
)
def test_each_protocol_answers_the_devices_meant_for_it(
    simulation: MimirApp, protocol: type, devices: set[str]
) -> None:
    """Answer a presenter's device protocol with exactly the devices it drives."""
    assert set(satisfying(simulation.devices, protocol)) == devices


def test_the_positioner_holds_every_stage_axis(simulation: MimirApp) -> None:
    """Find every axis of the simulated stages in redsun's positioner."""
    axes = {device: set(found) for device, found in simulation.motor_ctrl.axes.items()}
    assert axes == {"XY-axis": {"x", "y"}, "Z-axis": {"z"}}


def test_the_light_presenter_holds_every_light(simulation: MimirApp) -> None:
    """Find both lights in redsun's light presenter, the LED without an intensity."""
    lights = simulation.light_ctrl.lights
    assert set(lights) == {"laser", "led"}
    assert lights["laser"].intensity is not None
    assert lights["led"].intensity is None


def test_every_port_is_reached(simulation: MimirApp) -> None:
    """Leave no signal and no slot of the simulation without a link."""
    assert not simulation.unconnected, str(simulation.unconnected)


def test_the_simulation_makes_the_expected_links(simulation: MimirApp) -> None:
    """Make every link of the simulation, the built-in pairs' included."""
    actual = {
        (f"{c.publisher}.{c.publisher_port}", f"{c.consumer}.{c.consumer_port}")
        for c in simulation.connections
    }
    assert actual == SIMULATION_LINKS


def test_both_plans_are_offered_and_run(simulation: MimirApp) -> None:
    """Offer both plans in the acquisition view and its presenter."""
    plans = {"live_stream", "live_median_scan"}
    assert set(simulation.acq_widget.plan_widgets) == plans
    assert set(simulation.acq_ctrl.plans) == plans
