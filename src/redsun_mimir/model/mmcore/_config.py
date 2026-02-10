from __future__ import annotations

from typing import TYPE_CHECKING

from attrs import define, field, validators

from .._config import DetectorModelInfo

if TYPE_CHECKING:
    from typing import Any

    from attrs import Attribute


def freeze_dict(input: dict[str, list[str]]) -> dict[str, list[str]]:
    """Convert a dictionary of lists to a dictionary of lists.

    Parameters
    ----------
    input : ``dict[str, list[str]]``
        Input dictionary with lists as values.

    Returns
    -------
    ``dict[str, list[str]]``
        Output dictionary with lists as values.

    """
    return {key: list(value) for key, value in input.items()}


def has_only_one_key(input: dict[str, dict[str, str]]) -> None:
    """Check if a dictionary of dictionaries has only one key.

    If the first level of the nested dictionary
    contains more than one key, it indicates that there are multiple properties
    providing data type information, which is not allowed in this context.

    Parameters
    ----------
    input : ``dict[str, dict[str, str]]``
        Input dictionary.

    Returns
    -------
    ``bool``
        True if the dictionary has only one key, False otherwise.

    """
    if len(input.keys()) > 1:
        raise ValueError(
            "The first level of the nested dictionary must contain only one key."
        )


@define(kw_only=True)
class MMCoreCameraModelInfo(DetectorModelInfo):
    """Configuration of a Micro-Manager camera detector model.

    When no configuration is provided,
    the model will fallback to the default values specified in this class.

    Overrides the ``vendor`` field from ``DetectorModelInfo``
    to set a default value of "Micro-Manager".
    """

    vendor: str = "Micro-Manager"
    adapter: str = field(validator=validators.instance_of(str), default="DemoCamera")
    """The Micro-Manager adapter name for the camera. Default is "DemoCam"."""

    device: str = field(validator=validators.instance_of(str), default="DCam")
    """The Micro-Manager device available for the specified ``adapter``. Default is "DCam"."""

    allowed_properties: list[str] = field(
        default=["PixelType"],
    )
    """Set of allowed Micro-Manager properties for the camera."""

    defaults: dict[str, Any] = field(factory=dict)
    """
    Map of default values for the allowed properties.

    The keys must match the values in ``allowed_properties``.

    Defaults to an empty dictionary (the built-in defaults of the camera will be used).
    """

    starting_exposure: float = field(
        validator=validators.instance_of(float),
        default=100.0,
    )
    """Starting exposure time in milliseconds for the camera. Default is 100 ms."""

    exposure_limits: tuple[float, float] = field(
        converter=tuple,
        validator=validators.instance_of(tuple),
        default=(0.0, 10000.0),
    )
    """Mimum and maximum exposure time in milliseconds for the camera. Default is (0.0, 10000.0) ms."""

    enum_map: dict[str, list[str]] = field(
        converter=freeze_dict,
        default={
            "PixelType": ["8bit", "16bit", "32bit"],
        },
    )
    """A map of values for properties that support enumerated values."""

    numpy_dtype: dict[str, dict[str, str]] = field(
        default={
            "PixelType": {
                "8bit": "uint8",
                "16bit": "uint16",
                "32bit": "float32",
            }
        },
    )
    """
    A nested dictionary where the first key is the property name
    that provides data type information of the aquired images
    and the nested dictionary maps the property values to corresponding NumPy data types.
    The property name must be one of the allowed properties in ``allowed_properties``,
    and the property values must match the values specified in the ``enum_map`` for that property.

    The first level must contain only one key.
    """

    @numpy_dtype.validator
    def _has_only_one_key(
        self,
        attribute: Attribute[dict[str, dict[str, str]]],
        value: dict[str, dict[str, str]],
    ) -> None:
        if len(value.keys()) > 1:
            raise ValueError(
                "The first level of the nested dictionary must contain only one key."
            )
