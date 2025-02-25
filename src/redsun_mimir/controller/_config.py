from __future__ import annotations

from typing import Optional

from attrs import define, field, validators
from sunflare.config import ControllerInfo

__all__ = ["StageControllerInfo"]


@define
class StageControllerInfo(ControllerInfo):
    """Configuration class for the stage controller.

    Parameters
    ----------
    timeout : ``float``, optional
        Timeout in seconds.
        If a motor doesn't reach the requested position within this time,
        the controller will raise an exception.
        Default is ``None`` (no timeout, wait indefinitely).

    """

    timeout: Optional[float] = field(
        default=None, validator=validators.optional(validators.instance_of(float))
    )
