from __future__ import annotations

import logging
from pathlib import Path

from redsun.containers import (
    declare_device,
    declare_hook,
    declare_presenter,
    declare_view,
)
from redsun.presenter.builtins import StoragePresenter
from redsun.qt import QtAppContainer
from redsun.view.qt.builtins import StorageView

from ._wiring import (
    wire_acquisition,
    wire_detector,
    wire_light,
    wire_median,
    wire_motor,
)

_CONFIG = Path(__file__).parent / "full_configuration.yaml"


def build_simulation_container() -> QtAppContainer:
    """Return the example container, unbuilt (see `build_acquisition_container`)."""
    # devices
    from redsun_mimir.device import MockLightDevice
    from redsun_mimir.device.mmcore import MMDemoCamera, MMDemoXYStage, MMDemoZStage

    # hooks
    from redsun_mimir.hooks import NapariApplication

    # presenters
    from redsun_mimir.presenter.acquisition import AcquisitionPresenter
    from redsun_mimir.presenter.detector import DetectorPresenter
    from redsun_mimir.presenter.light import LightPresenter
    from redsun_mimir.presenter.median import MedianPresenter
    from redsun_mimir.presenter.motor import MotorPresenter

    # views
    from redsun_mimir.view.acquisition import AcquisitionView
    from redsun_mimir.view.detector import DetectorView
    from redsun_mimir.view.image import ImageView
    from redsun_mimir.view.light import LightView
    from redsun_mimir.view.motor import MotorView

    logging.getLogger("redsun").setLevel(logging.DEBUG)

    napari_app = NapariApplication()

    class MimirSimulator(QtAppContainer, config=_CONFIG):
        # one object at both points: the theme it applies is the one it
        # restores on shutdown
        create_application = declare_hook(napari_app)
        configure_application = declare_hook(napari_app)

        # devices
        mmcamera = declare_device(MMDemoCamera, from_config="camera1")
        XY = declare_device(MMDemoXYStage, from_config="xy-motor")
        Z = declare_device(MMDemoZStage, from_config="z-motor")
        laser = declare_device(MockLightDevice, from_config="laser")
        led = declare_device(MockLightDevice, from_config="led")

        # presenters
        storage_ctrl = declare_presenter(StoragePresenter, from_config="storage_ctrl")
        median_ctrl = declare_presenter(MedianPresenter, from_config="median_ctrl")
        det_ctrl = declare_presenter(DetectorPresenter, from_config="det_ctrl")
        acq_ctrl = declare_presenter(AcquisitionPresenter, from_config="acq_ctrl")
        light_ctrl = declare_presenter(LightPresenter, from_config="light_ctrl")
        motor_ctrl = declare_presenter(MotorPresenter, from_config="motor_ctrl")

        # views
        acq_widget = declare_view(AcquisitionView, from_config="acq_widget")
        img_widget = declare_view(ImageView, from_config="img_widget")
        det_widget = declare_view(DetectorView, from_config="det_widget")
        light_widget = declare_view(LightView, from_config="light_widget")
        motor_widget = declare_view(MotorView, from_config="motor_widget")
        storage_widget = declare_view(StorageView, from_config="storage_widget")

        def wire(self) -> None:
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

    return MimirSimulator()


def run_simulation_container() -> None:
    """Run a local mock example.

    Launches a simulation with the full stack
    provided by mimir with mock devices.
    """
    build_simulation_container().run()
