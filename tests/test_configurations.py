"""Smoke tests for the shipped example containers.

These containers are user-facing artifacts reachable from the ``mimir`` CLI,
but nothing imported them until now - which is exactly how they came to
reference a device layer that no longer existed. Building them exercises the
whole declaration path: every device, presenter and view class resolves, the
YAML session files match the declarations, and redsun's build phases run to
completion.

``run()`` is never called: it enters the Qt event loop and never returns.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from redsun.presenter import PPresenter
from redsun.view import PView

from redsun_mimir.configurations import (
    build_simulation_container,
    build_uc2_container,
)

from .conftest import HAS_OPENGL, NO_OPENGL_REASON

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from redsun.qt import QtAppContainer

pytestmark = pytest.mark.qt


#: Declared by `MimirApp`, so every session has them whatever its hardware.
_SHARED_PRESENTERS = {
    "median_ctrl",
    "det_ctrl",
    "acq_ctrl",
    "light_ctrl",
    "motor_ctrl",
}
_SHARED_VIEWS = {
    "acq_widget",
    "img_widget",
    "det_widget",
    "light_widget",
    "motor_widget",
}

_SIMULATION_DEVICES = {"mmcamera", "XY", "Z", "laser", "led"}


@pytest.fixture
def simulation() -> Iterator[QtAppContainer]:
    """Return the built simulation container, shut down after the test.

    Building it needs a real OpenGL context for the napari viewer, so a test
    taking it is skipped headless. A mark cannot do that from a fixture.
    """
    if not HAS_OPENGL:
        pytest.skip(NO_OPENGL_REASON)
    container = build_simulation_container()
    try:
        container.build()
        yield container
    finally:
        container.shutdown()


@pytest.mark.parametrize(
    ("factory", "session_file", "devices"),
    [
        pytest.param(
            build_simulation_container,
            "full_configuration.yaml",
            {"mmcamera", "XY", "Z", "laser", "led"},
            id="simulation",
        ),
        pytest.param(
            build_uc2_container,
            "uc2_full_configuration.yaml",
            {"iscat", "stage", "laser"},
            id="uc2",
        ),
    ],
)
def test_a_session_declares_only_its_devices(
    factory: Callable[[], QtAppContainer],
    session_file: str,
    devices: set[str],
) -> None:
    """Both sessions take the same presenters, views and hooks from the base.

    Nothing is built, so this covers the UC2 session too, whose hardware no
    test machine has. The declarations are the thing being checked: the two
    sessions differ in their devices and in the file that configures them, and
    in nothing else.
    """
    cls = type(factory())

    assert set(cls._device_components) == devices
    assert set(cls._presenter_components) == _SHARED_PRESENTERS
    assert set(cls._view_components) == _SHARED_VIEWS
    assert set(cls._hook_providers) == {"create_application", "configure_application"}
    # the common file first, the session's own laid over it
    assert [path.name for path in cls._config_paths] == [
        "common_configuration.yaml",
        session_file,
    ]


def test_container_builds_every_component(simulation: QtAppContainer) -> None:
    """Every declared component comes up, and presenters/views satisfy the protocols.

    Device build failures are logged and skipped by redsun rather than
    raising, so asserting on the device names is the only way a missing or
    misdeclared device surfaces here.
    """
    assert set(simulation.devices) == _SIMULATION_DEVICES
    assert set(simulation.presenters) == _SHARED_PRESENTERS
    assert set(simulation.views) == _SHARED_VIEWS

    for presenter in simulation.presenters.values():
        assert isinstance(presenter, PPresenter)
    for view in simulation.views.values():
        assert isinstance(view, PView)


def test_every_slot_is_reached(simulation: QtAppContainer) -> None:
    """No marked slot is left without a publisher.

    A misspelled port fails at build; a connection nobody wrote fails
    nowhere. Every ``@slot`` in this bundle exists because something is meant
    to reach it, so an entry here is a line missing from ``wire()``.

    Only slots: a container legitimately declares components offering signals
    it does not use, so ``unconnected.signals`` is expected to be non-empty.
    """
    report = simulation.virtual_container.unconnected
    assert report.slots == [], str(report)


#: Expected wiring graph per container, as ``(publisher.port, consumer.port)``.
#: Derived from `redsun_mimir.configurations._wiring`; the containers behind
#: `needs_opengl` cannot be built without a display, so their entries are
#: verified by this test only where one exists.
_DETECTOR_LINKS = {
    ("det_ctrl.sig_new_data", "img_widget.update_layers"),
    ("det_widget.sig_property_changed", "det_ctrl.set"),
    ("det_ctrl.sig_new_configuration", "det_widget.on_new_configuration"),
}
_MEDIAN_LINKS = {
    ("median_ctrl.median", "img_widget.update_layers"),
    ("median_ctrl.filtered", "img_widget.update_layers"),
}
_ACQUISITION_LINKS = {
    ("acq_widget.sig_launch_plan_request", "acq_ctrl.launch_plan"),
    ("acq_widget.sig_stop_plan_request", "acq_ctrl.stop_plan"),
    ("acq_widget.sig_pause_resume_request", "acq_ctrl.pause_or_resume_plan"),
    ("acq_widget.sig_action_request", "acq_ctrl.toggle_action_event"),
    ("acq_ctrl.sig_plan_done", "acq_widget.on_plan_done"),
    ("acq_ctrl.sig_action_done", "acq_widget.on_action_done"),
    ("acq_ctrl.sig_pre_launch_notify", "median_ctrl.clear_medians"),
    ("acq_ctrl.sig_pre_launch_notify", "path_provider.set_plan"),
    ("acq_ctrl.sig_plan_done", "path_provider.reset_plan"),
}
_FULL_LINKS = (
    _DETECTOR_LINKS
    | _MEDIAN_LINKS
    | _ACQUISITION_LINKS
    | {
        ("motor_widget.sig_motor_move", "motor_ctrl.move"),
        ("light_widget.sig_toggle_light_request", "light_ctrl.trigger"),
        ("light_widget.sig_intensity_request", "light_ctrl.set"),
    }
)


def test_container_declares_the_expected_graph(simulation: QtAppContainer) -> None:
    """The whole wiring graph, not a sample of it.

    `test_every_slot_is_reached` catches a line nobody wrote; this catches
    one written wrong, and pins the fan-in that is easiest to get subtly
    incorrect (three publishers reach ``img_widget.update_layers``).
    """
    actual = {
        (
            f"{link.publisher}.{link.publisher_port}",
            f"{link.consumer}.{link.consumer_port}",
        )
        for link in simulation.virtual_container.connections
    }
    assert actual == _FULL_LINKS


_EXPECTED_SUBSCRIPTIONS = {
    ("XY-axis-x", "motor_widget.update_setpoint"),
    ("XY-axis-y", "motor_widget.update_setpoint"),
    ("Z-axis-z", "motor_widget.update_setpoint"),
}


def test_container_declares_the_expected_subscriptions(
    simulation: QtAppContainer,
) -> None:
    """Every axis readback reaches the position labels.

    These are not declared in ``wire()``: the view subscribes to them while
    injecting its dependencies, so an axis silently missing from the map would
    leave one label frozen and nothing else would notice.
    """
    actual = {
        (record.source, f"{record.consumer}.{record.consumer_port}")
        for record in simulation.virtual_container.subscriptions
    }
    assert actual == _EXPECTED_SUBSCRIPTIONS
