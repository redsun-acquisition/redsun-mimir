from __future__ import annotations

from typing import TYPE_CHECKING

from attrs import define, field, validators

if TYPE_CHECKING:
    from typing import Any

    from attrs import Attribute

__all__ = ["MotorControllerInfo", "LightControllerInfo"]


@define
class _CommonControllerInfo:
    """Common configuration class for controllers.

    Parameters
    ----------
    timeout : ``float``, optional
        Timeout in seconds.
        If a presenter doesn't reach the requested state within this time,
        the presenter will raise an exception.
        Default is ``None`` (no timeout, wait indefinitely).

    """

    timeout: float | None = field(
        default=None, validator=validators.optional(validators.instance_of(float))
    )


class MotorControllerInfo(_CommonControllerInfo):
    """Configuration class for the stage presenter."""

    ...


class LightControllerInfo(_CommonControllerInfo):
    """Configuration class for the light presenter."""

    ...


class DetectorControllerInfo(_CommonControllerInfo):
    """Configuration class for the detector presenter."""

    ...


@define(kw_only=True)
class AcquisitionControllerInfo(_CommonControllerInfo):
    """Configuration class for the acquisition presenter.

    Parameters
    ----------
    debug : ``bool``, optional
        Enable additional debugging output.
        Default is ``False``.
    metadata : ``dict[str, Any]``, optional
        Additional metadata for the presenter's engine.
        Default is an empty dictionary.

    """

    debug: bool = field(default=False, validator=validators.instance_of(bool))
    metadata: dict[str, Any] = field(default={}, validator=validators.instance_of(dict))
    callbacks: list[str] = field(
        default=["DetectorController"], validator=validators.instance_of(list)
    )

    @callbacks.validator
    def _validate_callbacks(
        self, attribute: Attribute[list[str]], value: list[str]
    ) -> None:
        if any(not isinstance(item, str) for item in value):
            raise ValueError(f"All items in {attribute.name} must be of type 'str'.")


class ImageControllerInfo(_CommonControllerInfo):
    """Configuration class for the image visualization presenter."""

    ...


class RendererControllerInfo(_CommonControllerInfo):
    """Configuration class for the a presenter."""

    ...
