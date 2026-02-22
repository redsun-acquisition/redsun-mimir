from __future__ import annotations

import logging
from pathlib import Path

import yaml
from redsun.containers import device, presenter, view
from redsun.qt import QtAppContainer

_CONFIG = Path(__file__).parent / "acquisition_configuration.yaml"


def run_acquisition_container() -> None:
    """Run a local mock example.

    Launches a Qt ``AcquisitionView`` app with a background
    ``DetectorPresenter`` and ``MedianPresenter``.
    """
    from redsun_mimir.device import MockMotorDevice
    from redsun_mimir.device.mmcore import MMCoreCameraDevice
    from redsun_mimir.presenter import (
        AcquisitionPresenter,
        DetectorPresenter,
        MedianPresenter,
    )
    from redsun_mimir.view import AcquisitionView, DetectorView, ImageView

    logging.getLogger("redsun").setLevel(logging.DEBUG)

    class AcquisitionDetectorApp(QtAppContainer, config=_CONFIG):
        mmcore = device(MMCoreCameraDevice, from_config="camera1")
        motor = device(MockMotorDevice, from_config="motor")
        median_ctrl = presenter(MedianPresenter, from_config="median_ctrl")
        det_ctrl = presenter(DetectorPresenter, from_config="det_ctrl")
        acq_ctrl = presenter(AcquisitionPresenter, from_config="acq_ctrl")
        acq_widget = view(AcquisitionView, from_config="acq_widget")
        img_widget = view(ImageView, from_config="img_widget")
        det_widget = view(DetectorView, from_config="det_widget")

        def __init__(self, **kwargs: object) -> None:
            super().__init__(**kwargs)
            # AppContainerMeta loads the YAML only to resolve component kwargs;
            # the storage section is never written into _config in the declarative
            # path (unlike from_config() which does this explicitly).  We read it
            # here so that build() can find and inject the shared Writer.
            with open(_CONFIG) as fh:
                _yaml = yaml.safe_load(fh)
            storage_cfg = _yaml.get("storage")
            if storage_cfg is not None:
                self._config["storage"] = storage_cfg

    AcquisitionDetectorApp().run()
