"""Links shared by the example sessions.

Each helper takes the components it links, not the session, so every port is
checked against the class declaring it, and yields each link for the session
to make.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    from redsun import Link
    from redsun.path_provider import SessionPathProvider

    from redsun_mimir.presenter.acquisition import AcquisitionPresenter
    from redsun_mimir.presenter.detector import DetectorPresenter
    from redsun_mimir.presenter.light import LightPresenter
    from redsun_mimir.presenter.median import MedianPresenter
    from redsun_mimir.presenter.motor import MotorPresenter
    from redsun_mimir.view.acquisition import AcquisitionView
    from redsun_mimir.view.detector import DetectorView
    from redsun_mimir.view.image import ImageView
    from redsun_mimir.view.light import LightView
    from redsun_mimir.view.motor import MotorView

__all__ = [
    "wire_acquisition",
    "wire_detector",
    "wire_light",
    "wire_locks",
    "wire_median",
    "wire_motor",
]


def wire_detector(
    ctrl: DetectorPresenter, view: DetectorView, image: ImageView
) -> Iterator[Link]:
    """Link the detector presenter, its settings view, and the viewer."""
    yield ctrl.sig_new_data, image.update_layers
    yield view.sig_property_changed, ctrl.set
    yield ctrl.sig_new_configuration, view.on_new_configuration
    yield ctrl.sig_new_configuration, image.on_new_configuration
    yield image.sig_roi_drawn, view.on_roi_drawn
    yield view.sig_roi_selection, image.set_roi_selection
    yield view.sig_roi_edited, image.set_roi_box


def wire_median(ctrl: MedianPresenter, image: ImageView) -> Iterator[Link]:
    """Route both median streams to the viewer, each as its own layer."""
    yield ctrl.frames.median, image.update_layers
    yield ctrl.frames.filtered, image.update_layers


def wire_motor(ctrl: MotorPresenter, view: MotorView) -> Iterator[Link]:
    """Link stage step requests, and every axis readback to its label.

    The labels follow the readbacks, not the presenter, so they show moves
    the presenter never made.
    """
    yield view.sig_motor_move, ctrl.move
    for readback in ctrl.devices_readbacks().values():
        yield readback, view.update_setpoint


def wire_light(ctrl: LightPresenter, view: LightView) -> Iterator[Link]:
    """Link the light source controls."""
    yield view.sig_toggle_light_request, ctrl.trigger
    yield view.sig_intensity_request, ctrl.set


def wire_acquisition(
    ctrl: AcquisitionPresenter,
    view: AcquisitionView,
    median: MedianPresenter,
    paths: SessionPathProvider,
) -> Iterator[Link]:
    """Link run control, the plans' actions, and the plan lifecycle.

    The view asks the acquisition presenter for an action, which passes the
    request to the component offering the running plan, and follows the
    actions of both components offering plans. The path provider takes the plan name, which names
    the files a run writes, and the base directory, which the view lets a
    user choose while no plan runs.
    """
    yield view.sig_launch_plan_request, ctrl.launch_plan
    yield view.sig_stop_plan_request, ctrl.stop_plan
    yield view.sig_pause_resume_request, ctrl.pause_or_resume_plan
    yield ctrl.sig_plan_done, view.on_plan_done
    yield view.sig_action_request, ctrl.request_action
    for actions in (ctrl.actions, median.actions):
        yield actions.sig_changed, view.on_action_changed

    yield view.sig_base_dir_request, paths.set_base_dir
    yield paths.sig_base_dir_changed, view.on_base_dir_changed

    yield ctrl.sig_pre_launch_notify, paths.set_plan
    yield ctrl.sig_plan_done, paths.reset_plan

    yield ctrl.sig_pre_launch_notify, median.clear_medians


def wire_locks(
    ctrl: AcquisitionPresenter, *views: MotorView | LightView | DetectorView
) -> Iterator[Link]:
    """Disable, in each view, the controls of the devices a running plan holds."""
    for view in views:
        yield ctrl.sig_locks_changed, view.set_locked
