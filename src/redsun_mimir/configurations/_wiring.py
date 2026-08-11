"""Connections shared by the example containers.

Each helper takes the components it connects rather than the container, so
every port is checked against the class that declares it. Passing the
container instead would type each component as ``Any`` and lose exactly the
check these declarations exist for.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redsun.containers import AppContainer
    from redsun.presenter.builtins import StoragePresenter

    from redsun_mimir.presenter.acquisition import AcquisitionPresenter
    from redsun_mimir.presenter.detector import DetectorPresenter
    from redsun_mimir.presenter.filterwheel import FilterWheelPresenter
    from redsun_mimir.presenter.light import LightPresenter
    from redsun_mimir.presenter.median import MedianPresenter
    from redsun_mimir.presenter.motor import MotorPresenter
    from redsun_mimir.view.acquisition import AcquisitionView
    from redsun_mimir.view.detector import DetectorView
    from redsun_mimir.view.filterwheel import FilterWheelView
    from redsun_mimir.view.image import ImageView
    from redsun_mimir.view.light import LightView
    from redsun_mimir.view.motor import MotorView

__all__ = [
    "wire_acquisition",
    "wire_detector",
    "wire_filterwheel",
    "wire_light",
    "wire_median",
    "wire_motor",
]


def wire_detector(
    app: AppContainer,
    ctrl: DetectorPresenter,
    view: DetectorView,
    image: ImageView,
) -> None:
    """Connect the detector presenter, its settings view, and the viewer."""
    app.connect(ctrl.sig_new_data, image.update_layers)
    app.connect(view.sig_property_changed, ctrl.set)
    app.connect(ctrl.sig_new_configuration, view.on_new_configuration)


def wire_median(app: AppContainer, ctrl: MedianPresenter, image: ImageView) -> None:
    """Route both median streams to the viewer, each as its own layer."""
    app.connect(ctrl.frames.median, image.update_layers)
    app.connect(ctrl.frames.filtered, image.update_layers)


def wire_motor(app: AppContainer, ctrl: MotorPresenter, view: MotorView) -> None:
    """Connect stage step requests.

    The return path is not a connection: the view subscribes to the axis
    readbacks itself, so it also follows moves this presenter never made.
    """
    app.connect(view.sig_motor_move, ctrl.move)


def wire_light(app: AppContainer, ctrl: LightPresenter, view: LightView) -> None:
    """Connect the light source controls."""
    app.connect(view.sig_toggle_light_request, ctrl.trigger)
    app.connect(view.sig_intensity_request, ctrl.set)


def wire_filterwheel(
    app: AppContainer, ctrl: FilterWheelPresenter, view: FilterWheelView
) -> None:
    """Connect filter wheel selection requests."""
    app.connect(view.sig_state_request, ctrl.set_state)


def wire_acquisition(
    app: AppContainer,
    ctrl: AcquisitionPresenter,
    view: AcquisitionView,
    storage: StoragePresenter | None = None,
    median: MedianPresenter | None = None,
) -> None:
    """Connect run control, and the plan lifecycle to whoever tracks it.

    *storage* and *median* are optional because not every container declares
    them; when present they learn the plan name from the same signal.
    """
    app.connect(view.sig_launch_plan_request, ctrl.launch_plan)
    app.connect(view.sig_stop_plan_request, ctrl.stop_plan)
    app.connect(view.sig_pause_resume_request, ctrl.pause_or_resume_plan)
    app.connect(view.sig_action_request, ctrl.toggle_action_event)
    app.connect(ctrl.sig_plan_done, view.on_plan_done)
    app.connect(ctrl.sig_action_done, view.on_action_done)

    if median is not None:
        app.connect(ctrl.sig_pre_launch_notify, median.clear_medians)
    if storage is not None:
        app.connect(ctrl.sig_pre_launch_notify, storage.set_plan)
        app.connect(ctrl.sig_plan_done, storage.reset_plan)
