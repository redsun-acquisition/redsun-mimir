from collections import OrderedDict
from typing import Any

from bluesky.protocols import Reading
from event_model.documents.event_descriptor import DataKey
from sunflare.engine import Status

from ._config import LightModelInfo


class MockLightModel:
    """Mock light source for simulation and testing purposes."""

    def __init__(self, name: str, model_info: LightModelInfo) -> None:
        self._name = name
        self._model_info = model_info
        self.enabled = False
        self.intensity = 0.0

    def configure(self, *args: Any, **kwargs: Any) -> tuple[Reading[Any], Reading[Any]]:
        """Configure the light source (DEPRECATED)."""
        raise DeprecationWarning(
            "Deprecated method. Will be removed from sunflare in future release."
        )

    def set(self, value: Any, **kwargs: Any) -> Status:
        """Set the intensity of the light source.

        .. note::

            **kwargs are ignored in this implementation.

        """
        if not isinstance(value, (int, float)):
            raise ValueError("Value must be a number.")
        s = Status()
        self.intensity = float(value)
        s.set_finished()
        return s

    def read(self) -> dict[str, Reading[float]]:
        """Read the current intensity of the light source."""
        return {"intensity": Reading(value=self.intensity, timestamp=0)}

    def describe(self) -> dict[str, DataKey]:
        """Describe the data keys of ``read``."""
        model_name = self.model_info.model_name
        return OrderedDict(
            {self.name: DataKey(source=model_name, dtype="number", shape=[])}
        )

    def read_configuration(self) -> dict[str, Reading[Any]]:
        return self.model_info.read_configuration()

    def describe_configuration(self) -> dict[str, DataKey]:
        return self.model_info.describe_configuration()

    def shutdown(self) -> None: ...

    def trigger(self) -> Status:
        """Toggle the activation status of the light source."""
        self.enabled = not self.enabled
        s = Status()
        s.set_finished()
        return s

    @property
    def name(self) -> str:
        return self._name

    @property
    def parent(self) -> None:
        return None

    @property
    def model_info(self) -> LightModelInfo:
        return self._model_info
