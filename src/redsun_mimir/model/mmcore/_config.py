from __future__ import annotations

from attrs import define, field, validators

from .._config import DetectorModelInfo


@define(kw_only=True)
class MMCoreCameraModelInfo(DetectorModelInfo):
    """Configuration of a Micro-Manager camera detector model.

    Overrides the ``vendor`` field from ``DetectorModelInfo``
    to set a default value of "Micro-Manager".

    Parameters
    ----------
    adapter: ``str``
        The Micro-Manager adapter name for the camera.
        Default is "DemoCam".
    device: ``str``
        The Micro-Manager device available for the specified ``adapter``.
        Default is "DCam".
    """

    vendor: str = "Micro-Manager"
    adapter: str = field(validator=validators.instance_of(str), default="DemoCamera")
    device: str = field(validator=validators.instance_of(str), default="DCam")
