"""Smoke tests for the shipped example sessions.

Building one exercises the whole declaration path: every device, presenter
and view class resolves, the YAML session files match the declarations, and
the build steps run to completion. `run()` is never called: it enters the Qt
event loop and never returns.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from redsun import Layer

from redsun_mimir.configurations import (
    build_simulation_container,
    build_uc2_container,
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
    ("motor_widget.sig_motor_move", "motor_ctrl.move"),
    ("XY.axis-x", "motor_widget.update_setpoint"),
    ("XY.axis-y", "motor_widget.update_setpoint"),
    ("Z.axis-z", "motor_widget.update_setpoint"),
    ("light_widget.sig_toggle_light_request", "light_ctrl.trigger"),
    ("light_widget.sig_intensity_request", "light_ctrl.set"),
    ("acq_widget.sig_launch_plan_request", "acq_ctrl.launch_plan"),
    ("acq_widget.sig_stop_plan_request", "acq_ctrl.stop_plan"),
    ("acq_widget.sig_pause_resume_request", "acq_ctrl.pause_or_resume_plan"),
    ("acq_ctrl.sig_plan_done", "acq_widget.on_plan_done"),
    ("acq_widget.sig_action_request", "acq_ctrl.request_action"),
    ("acq_ctrl.sig_changed", "acq_widget.on_action_changed"),
    ("median_ctrl.sig_changed", "acq_widget.on_action_changed"),
    ("acq_widget.sig_base_dir_request", "SessionPathProvider.set_base_dir"),
    ("SessionPathProvider.sig_base_dir_changed", "acq_widget.on_base_dir_changed"),
    ("acq_ctrl.sig_pre_launch_notify", "SessionPathProvider.set_plan"),
    ("acq_ctrl.sig_plan_done", "SessionPathProvider.reset_plan"),
    ("acq_ctrl.sig_pre_launch_notify", "median_ctrl.clear_medians"),
    ("acq_ctrl.sig_locks_changed", "det_widget.set_locked"),
    ("acq_ctrl.sig_locks_changed", "motor_widget.set_locked"),
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
        assert set(session.hooks) == {"create_application", "configure_application"}
    finally:
        session.shutdown()


def test_the_simulation_builds_every_component(simulation: MimirApp) -> None:
    """Build every device, presenter and view the simulation declares."""
    assert set(simulation.devices) == SIMULATION_DEVICES
    assert set(simulation.presenters) == SHARED_PRESENTERS
    assert set(simulation.views) == SHARED_VIEWS


def test_every_port_is_reached(simulation: MimirApp) -> None:
    """Leave no signal and no slot of the simulation without a link."""
    assert not simulation.unconnected, str(simulation.unconnected)


def test_the_simulation_makes_the_expected_links(simulation: MimirApp) -> None:
    """Make every link of the simulation, the axis readbacks included."""
    actual = {
        (f"{c.publisher}.{c.publisher_port}", f"{c.consumer}.{c.consumer_port}")
        for c in simulation.connections
    }
    assert actual == SIMULATION_LINKS


def test_both_plans_are_offered_and_run(simulation: MimirApp) -> None:
    """Offer both plans in the view, and run both from the presenter."""
    plans = {"live_stream", "live_median_scan"}
    assert set(simulation.acq_widget.plan_widgets) == plans
    assert set(simulation.acq_ctrl.plan_specs) == plans
