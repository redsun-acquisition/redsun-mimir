"""The session both examples are built on."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from redsun import AsHook, AsPresenter, AsView, Declare, Serves, links_between
from redsun.presenter import PositionerPresenter
from redsun.qt import QtHook, QtSession
from redsun.qt.styles.napari import NapariStyle
from redsun.view.qt.builtins import PositionerView

from redsun_mimir.hooks import FONT_SIZE, NapariApplication
from redsun_mimir.presenter.acquisition import AcquisitionPresenter
from redsun_mimir.presenter.detector import DetectorPresenter
from redsun_mimir.presenter.light import LightPresenter
from redsun_mimir.presenter.median import MedianPresenter
from redsun_mimir.view.acquisition import AcquisitionView
from redsun_mimir.view.detector import DetectorView
from redsun_mimir.view.image import ImageView
from redsun_mimir.view.light import LightView
from redsun_mimir.view.logs import LogsAction

from ._wiring import (
    wire_acquisition,
    wire_detector,
    wire_light,
    wire_locks,
    wire_median,
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

    napari: Annotated[AsHook[NapariApplication], Serves(QtHook.CREATE_APPLICATION)]
    style: Annotated[
        AsHook[NapariStyle],
        Serves(QtHook.CONFIGURE_APPLICATION),
        Declare(font_size=FONT_SIZE),
    ]

    median_ctrl: AsPresenter[MedianPresenter]
    det_ctrl: AsPresenter[DetectorPresenter]
    acq_ctrl: AsPresenter[AcquisitionPresenter]
    light_ctrl: AsPresenter[LightPresenter]
    motor_ctrl: AsPresenter[PositionerPresenter]

    acq_widget: AsView[AcquisitionView]
    img_widget: AsView[ImageView]
    det_widget: AsView[DetectorView]
    light_widget: AsView[LightView]
    motor_widget: AsView[PositionerView]
    logs: AsView[LogsAction]

    def wire(self) -> Iterator[Link]:
        """Link the presenters to the views."""
        yield from wire_detector(self.det_ctrl, self.det_widget, self.img_widget)
        yield from wire_median(self.median_ctrl, self.img_widget)
        yield from links_between(self.motor_widget, self.motor_ctrl)
        yield from wire_light(self.light_ctrl, self.light_widget)
        yield from wire_acquisition(
            self.acq_ctrl, self.acq_widget, self.median_ctrl, self.path_provider
        )
        yield from wire_locks(
            self.acq_ctrl,
            self.motor_ctrl,
            self.motor_widget,
            self.light_widget,
            self.det_widget,
        )
