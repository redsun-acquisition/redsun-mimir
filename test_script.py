# ruff: noqa

from __future__ import annotations

from redsun import declare_device, declare_presenter, declare_view
from redsun.qt import QtAppContainer

# from redsun_mimir.device.mmcore import MMDemoXYStage, MMDemoZStage
# from redsun_mimir.device import MockLightDevice
# from redsun_mimir.presenter.motor import MotorPresenter
# from redsun_mimir.presenter.light import LightPresenter
# from redsun_mimir.view.motor import MotorView
# from redsun_mimir.view.light import LightView


# class TestContainer(QtAppContainer):
#     motorxy = declare_device(MMDemoXYStage)
#     motorz = declare_device(MMDemoZStage)
#     light = declare_device(MockLightDevice, wavelength=488)
#     motor_presenter = declare_presenter(MotorPresenter)
#     light_presenter = declare_presenter(LightPresenter)
#     motor_view = declare_view(MotorView)
#     light_view = declare_view(LightView)

from redsun_mimir.device.mmcore import MMDemoCamera, MMDemoXYStage, MMDemoZStage
from redsun_mimir.presenter.detector import DetectorPresenter
from redsun_mimir.presenter.acquisition import AcquisitionPresenter
from redsun_mimir.presenter.median import MedianPresenter
from redsun_mimir.presenter.storage import FileStoragePresenter
from redsun_mimir.view.detector import DetectorView
from redsun_mimir.view.image import ImageView
from redsun_mimir.view.acquisition import AcquisitionView
from redsun_mimir.view.storage import FileStorageView


class TestContainer(QtAppContainer):
    camera = declare_device(MMDemoCamera)
    motorxy = declare_device(MMDemoXYStage)
    motorz = declare_device(MMDemoZStage)
    det_presenter = declare_presenter(DetectorPresenter)
    acq_presenter = declare_presenter(AcquisitionPresenter)
    median_presenter = declare_presenter(MedianPresenter)
    storage_presenter = declare_presenter(FileStoragePresenter)
    det_view = declare_view(DetectorView)
    image_view = declare_view(ImageView)
    acq_view = declare_view(AcquisitionView)
    storage_view = declare_view(FileStorageView)


app = TestContainer()
app.run()
