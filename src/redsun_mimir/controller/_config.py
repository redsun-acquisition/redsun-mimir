from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from attrs import define, field, validators
from sunflare.config import ControllerInfo

if TYPE_CHECKING:
    from collections.abc import Callable

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


@define(kw_only=True)
class AcquisitionControllerInfo(_CommonControllerInfo):
    """Configuration class for the acquisition controller.

    Parameters
    ----------
    metadata : ``dict[str, Any]``, optional
        Additional metadata for the controller's engine.
        Default is an empty dictionary.

    """

    metadata: dict[str, Any] = field(default={}, validator=validators.instance_of(dict))

    # private attribute;
    # initialized from the controller
    plans: dict[str, Callable[..., None]] = field(init=False)
