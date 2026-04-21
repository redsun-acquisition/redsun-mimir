# ruff: noqa

from __future__ import annotations

from redsun_mimir.device.mmcore import MMDemoXYStage, MMDemoZStage
from redsun_mimir.device import MockLightDevice
from redsun_mimir.presenter.motor import MotorPresenter
from redsun_mimir.presenter.light import LightPresenter
from redsun_mimir.view.motor import MotorView
from redsun_mimir.view.light import LightView
# from redsun_mimir.device import MockLightDevice

from redsun import declare_device, declare_presenter, declare_view
from redsun.qt import QtAppContainer


class TestContainer(QtAppContainer):
    motorxy = declare_device(MMDemoXYStage)
    motorz = declare_device(MMDemoZStage)
    light = declare_device(MockLightDevice, wavelength=488)
    motor_presenter = declare_presenter(MotorPresenter)
    light_presenter = declare_presenter(LightPresenter)
    motor_view = declare_view(MotorView)
    light_view = declare_view(LightView)


app = TestContainer()
app.run()
