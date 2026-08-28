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

from redsun_mimir.configurations import build_simulation_container

from .conftest import needs_opengl

if TYPE_CHECKING:
    from collections.abc import Callable

    from redsun.qt import QtAppContainer

pytestmark = pytest.mark.qt


_CONTAINERS = [
    pytest.param(
        build_simulation_container,
        {"mmcamera", "XY", "Z", "laser", "led"},
        {
            "storage_ctrl",
            "median_ctrl",
            "det_ctrl",
            "acq_ctrl",
            "light_ctrl",
            "motor_ctrl",
        },
        {
            "acq_widget",
            "img_widget",
            "det_widget",
            "light_widget",
            "motor_widget",
            "storage_widget",
        },
        id="simulation",
        marks=needs_opengl,
    ),
]


@pytest.mark.parametrize(("factory", "devices", "presenters", "views"), _CONTAINERS)
def test_container_builds_every_component(
    factory: Callable[[], QtAppContainer],
    devices: set[str],
    presenters: set[str],
    views: set[str],
) -> None:
    """Every declared component comes up, and presenters/views satisfy the protocols.

    Device build failures are logged and skipped by redsun rather than
    raising, so asserting on the device names is the only way a missing or
    misdeclared device surfaces here.
    """
    container = factory()
    try:
        container.build()

        assert set(container.devices) == devices
        assert set(container.presenters) == presenters
        assert set(container.views) == views

        for presenter in container.presenters.values():
            assert isinstance(presenter, PPresenter)
        for view in container.views.values():
            assert isinstance(view, PView)
    finally:
        container.shutdown()


_FACTORIES = [
    pytest.param(build_simulation_container, id="simulation", marks=needs_opengl),
]


@pytest.mark.parametrize("factory", _FACTORIES)
def test_every_slot_is_reached(factory: Callable[[], QtAppContainer]) -> None:
    """No marked slot is left without a publisher.

    A misspelled port fails at build; a connection nobody wrote fails
    nowhere. Every ``@slot`` in this bundle exists because something is meant
    to reach it, so an entry here is a line missing from ``wire()``.

    Only slots: a container legitimately declares components offering signals
    it does not use, so ``unconnected.signals`` is expected to be non-empty.
    """
    container = factory()
    try:
        container.build()

        report = container.virtual_container.unconnected
        assert report.slots == [], str(report)
    finally:
        container.shutdown()


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
    ("acq_ctrl.sig_pre_launch_notify", "storage_ctrl.set_plan"),
    ("acq_ctrl.sig_plan_done", "storage_ctrl.reset_plan"),
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

_GRAPHS = [
    pytest.param(
        build_simulation_container,
        _FULL_LINKS,
        id="simulation",
        marks=needs_opengl,
    ),
]


@pytest.mark.parametrize(("factory", "expected"), _GRAPHS)
def test_container_declares_the_expected_graph(
    factory: Callable[[], QtAppContainer],
    expected: set[tuple[str, str]],
) -> None:
    """The whole wiring graph, not a sample of it.

    `test_every_slot_is_reached` catches a line nobody wrote; this catches
    one written wrong, and pins the fan-in that is easiest to get subtly
    incorrect (three publishers reach ``img_widget.update_layers``).
    """
    container = factory()
    try:
        container.build()

        actual = {
            (
                f"{link.publisher}.{link.publisher_port}",
                f"{link.consumer}.{link.consumer_port}",
            )
            for link in container.virtual_container.connections
        }
        assert actual == expected
    finally:
        container.shutdown()


_SUBSCRIPTIONS = [
    pytest.param(
        build_simulation_container,
        {
            ("XY-axis-x", "motor_widget.update_setpoint"),
            ("XY-axis-y", "motor_widget.update_setpoint"),
            ("Z-axis-z", "motor_widget.update_setpoint"),
            # the storage view follows the session path provider, whose soft
            # signal carries no name, hence the empty source
            ("", "storage_widget.update_base_dir"),
        },
        id="simulation",
        marks=needs_opengl,
    ),
]


@pytest.mark.parametrize(("factory", "expected"), _SUBSCRIPTIONS)
def test_container_declares_the_expected_subscriptions(
    factory: Callable[[], QtAppContainer],
    expected: set[tuple[str, str]],
) -> None:
    """Every axis readback reaches the position labels.

    These are not declared in ``wire()``: the view subscribes to them while
    injecting its dependencies, so an axis silently missing from the map would
    leave one label frozen and nothing else would notice.
    """
    container = factory()
    try:
        container.build()

        actual = {
            (record.source, f"{record.consumer}.{record.consumer_port}")
            for record in container.virtual_container.subscriptions
        }
        assert actual == expected
    finally:
        container.shutdown()
