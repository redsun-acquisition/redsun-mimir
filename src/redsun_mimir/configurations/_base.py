"""The session both examples are built on."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from redsun import AsHook, AsPresenter, AsView, Serves
from redsun.qt import QtHook, QtSession
from redsun.view.qt.builtins import LogView

from redsun_mimir.hooks import NapariApplication
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

from ._wiring import (
    wire_acquisition,
    wire_detector,
    wire_light,
    wire_locks,
    wire_median,
    wire_motor,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from redsun import Link

__all__ = ["MimirApp"]

COMMON_CONFIG = Path(__file__).parent / "common_configuration.yaml"


class MimirApp(QtSession):
    """Every part of a Mimir session that does not depend on the hardware.

    A session subclasses this, declares its devices and names their
    configuration file; the presenters, the views, their configuration and
    their wiring come from here.
    """

    config = COMMON_CONFIG

    napari: Annotated[
        AsHook[NapariApplication],
        Serves(QtHook.CREATE_APPLICATION, QtHook.CONFIGURE_APPLICATION),
    ]

    median_ctrl: AsPresenter[MedianPresenter]
    det_ctrl: AsPresenter[DetectorPresenter]
    acq_ctrl: AsPresenter[AcquisitionPresenter]
    light_ctrl: AsPresenter[LightPresenter]
    motor_ctrl: AsPresenter[MotorPresenter]

    acq_widget: AsView[AcquisitionView]
    img_widget: AsView[ImageView]
    det_widget: AsView[DetectorView]
    light_widget: AsView[LightView]
    motor_widget: AsView[MotorView]
    logs: AsView[LogView]

    def wire(self) -> Iterator[Link]:
        """Link the presenters to the views."""
        yield from wire_detector(self.det_ctrl, self.det_widget, self.img_widget)
        yield from wire_median(self.median_ctrl, self.img_widget)
        yield from wire_motor(self.motor_ctrl, self.motor_widget)
        yield from wire_light(self.light_ctrl, self.light_widget)
        yield from wire_acquisition(
            self.acq_ctrl, self.acq_widget, self.median_ctrl, self.path_provider
        )
        yield from wire_locks(
            self.acq_ctrl, self.motor_widget, self.light_widget, self.det_widget
        )
        yield self.acq_ctrl.sig_pre_launch_notify, self.det_widget.clear_frames_written
