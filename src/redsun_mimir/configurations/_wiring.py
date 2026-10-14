"""Links shared by the example sessions.

Each helper takes the components it links, not the session, so every port is
checked against the class declaring it, and yields each link for the session
to make.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterator

    from redsun import Link
    from redsun.presenter import AcquisitionPresenter

    from redsun_mimir.presenter.detector import DetectorPresenter
    from redsun_mimir.presenter.median import MedianPresenter
    from redsun_mimir.view.detector import DetectorView
    from redsun_mimir.view.image import ImageView

__all__ = [
    "wire_detector",
    "wire_locks",
    "wire_median",
]


class HasLocked(Protocol):
    """A component told which devices a running plan holds."""

    def set_locked(self, names: frozenset[str]) -> None: ...


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


def wire_median(
    ctrl: MedianPresenter, image: ImageView, acquisition: AcquisitionPresenter
) -> Iterator[Link]:
    """Route both median streams to the viewer, each as its own layer.

    The cached medians are cleared whenever a plan starts.
    """
    yield ctrl.frames.median, image.update_layers
    yield ctrl.frames.filtered, image.update_layers
    yield acquisition.sig_plan_started, ctrl.clear_medians


def wire_locks(
    ctrl: AcquisitionPresenter,
    *holders: HasLocked,
) -> Iterator[Link]:
    """Tell each component which devices a running plan holds.

    A view disables their controls; the positioner refuses to move them by hand.
    """
    for holder in holders:
        yield ctrl.sig_locks_changed, holder.set_locked
