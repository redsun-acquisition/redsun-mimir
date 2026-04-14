from __future__ import annotations

import logging
from pathlib import Path

from redsun.containers import device, presenter, view
from redsun.qt import QtAppContainer

_CONFIG = Path(__file__).parent / "full_configuration.yaml"


def run_simulation_container() -> None:
    """Run a local mock example.

    Launches a simulation with the full stack
    provided by mimir with mock devices.
    """
    # devices
    from redsun_mimir.device import MockLightDevice  # noqa: I001
    from redsun_mimir.device.mmcore import MMCoreCameraDevice, MMCoreStageDevice  # noqa: I001

    # presenters
    from redsun_mimir.presenter.storage import FileStoragePresenter
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
    from redsun_mimir.view.storage import FileStorageView

    from redsun.storage._zarr import ZarrWriter

    logging.getLogger("redsun").setLevel(logging.DEBUG)

    _writer = ZarrWriter("default")

    class MimirSimulator(QtAppContainer, config=_CONFIG):
        # devices
        mmcore = device(MMCoreCameraDevice, from_config="camera1", writer=_writer)
        XY = device(MMCoreStageDevice, from_config="xy-motor")
        Z = device(MMCoreStageDevice, from_config="z-motor")
        laser = device(MockLightDevice, from_config="laser")
        led = device(MockLightDevice, from_config="led")

        # presenters
        storage_ctrl = presenter(FileStoragePresenter, from_config="storage_ctrl")
        median_ctrl = presenter(MedianPresenter, from_config="median_ctrl")
        det_ctrl = presenter(DetectorPresenter, from_config="det_ctrl")
        acq_ctrl = presenter(AcquisitionPresenter, from_config="acq_ctrl")
        light_ctrl = presenter(LightPresenter, from_config="light_ctrl")
        motor_ctrl = presenter(MotorPresenter, from_config="motor_ctrl")

        # views
        acq_widget = view(AcquisitionView, from_config="acq_widget")
        img_widget = view(ImageView, from_config="img_widget")
        det_widget = view(DetectorView, from_config="det_widget")
        light_widget = view(LightView, from_config="light_widget")
        motor_widget = view(MotorView, from_config="motor_widget")
        storage_widget = view(FileStorageView, from_config="storage_widget")

    MimirSimulator().run()
