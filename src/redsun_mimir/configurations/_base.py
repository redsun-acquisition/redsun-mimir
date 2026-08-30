"""The container both example sessions are built on."""

from __future__ import annotations

from pathlib import Path

from redsun.containers import declare_hook, declare_presenter, declare_view
from redsun.presenter.builtins import StoragePresenter
from redsun.qt import QtAppContainer
from redsun.view.qt.builtins import StorageView

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
    wire_median,
    wire_motor,
)

__all__ = ["MimirApp"]

COMMON_CONFIG = Path(__file__).parent / "common_configuration.yaml"

# one object at both points: the application it builds is the one it styles
_napari_app = NapariApplication()


class MimirApp(QtAppContainer, config=COMMON_CONFIG):
    """Every part of a Mimir session that does not depend on the hardware.

    A session subclasses this, declares its devices and names the file that
    configures them; the presenters, the views, their configuration and the
    wiring between them come from here.
    """

    create_application = declare_hook(_napari_app)
    configure_application = declare_hook(_napari_app)

    storage_ctrl = declare_presenter(StoragePresenter, from_config="storage_ctrl")
    median_ctrl = declare_presenter(MedianPresenter, from_config="median_ctrl")
    det_ctrl = declare_presenter(DetectorPresenter, from_config="det_ctrl")
    acq_ctrl = declare_presenter(AcquisitionPresenter, from_config="acq_ctrl")
    light_ctrl = declare_presenter(LightPresenter, from_config="light_ctrl")
    motor_ctrl = declare_presenter(MotorPresenter, from_config="motor_ctrl")

    acq_widget = declare_view(AcquisitionView, from_config="acq_widget")
    img_widget = declare_view(ImageView, from_config="img_widget")
    det_widget = declare_view(DetectorView, from_config="det_widget")
    light_widget = declare_view(LightView, from_config="light_widget")
    motor_widget = declare_view(MotorView, from_config="motor_widget")
    storage_widget = declare_view(StorageView, from_config="storage_widget")

    def wire(self) -> None:
        """Connect the presenters to the views."""
        wire_detector(self, self.det_ctrl, self.det_widget, self.img_widget)
        wire_median(self, self.median_ctrl, self.img_widget)
        wire_motor(self, self.motor_ctrl, self.motor_widget)
        wire_light(self, self.light_ctrl, self.light_widget)
        wire_acquisition(
            self,
            self.acq_ctrl,
            self.acq_widget,
            storage=self.storage_ctrl,
            median=self.median_ctrl,
        )
