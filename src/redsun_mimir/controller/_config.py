from __future__ import annotations

from typing import Optional

from attrs import define, field, validators
from sunflare.config import ControllerInfo

__all__ = ["StageControllerInfo", "LightControllerInfo"]


@define
class _CommonControllerInfo(ControllerInfo):
    """Common configuration class for controllers.

    Parameters
    ----------
    timeout : ``float``, optional
        Timeout in seconds.
        If a controller doesn't reach the requested state within this time,
        the controller will raise an exception.
        Default is ``None`` (no timeout, wait indefinitely).

    """

    timeout: Optional[float] = field(
        default=None, validator=validators.optional(validators.instance_of(float))
    )


class StageControllerInfo(_CommonControllerInfo):
    """Configuration class for the stage controller."""

    ...


class LightControllerInfo(_CommonControllerInfo):
    """Configuration class for the light controller."""

    ...
