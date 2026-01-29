from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

from bluesky.protocols import Reading
from sunflare.engine import Status

from redsun_mimir.protocols import PseudoModelProtocol

if TYPE_CHECKING:
    from typing import Any

    from bluesky.protocols import Descriptor, Reading
    from sunflare.config import ModelInfo


class MedianPseudoModel(PseudoModelProtocol):
    """Pseudo-model that computes the median of stashed readings.

    Readings are stashed per device and the median computed
    along the time axis when `trigger()` is called.
    """

    def __init__(self, name: str, model_info: ModelInfo) -> None:
        self._name = name
        self._model_info = model_info
        self._stashed_readings: deque[dict[str, Reading[Any]]] = deque()
        self._datakey = f"PSEUDO:{self._name}"

    def describe(self) -> dict[str, Descriptor]:
        return {}

    def read(self) -> dict[str, Reading[Any]]:
        return {}

    def trigger(self) -> Status:
        s = Status()
        return s

    def stash(self, value: dict[str, Reading[Any]]) -> None:
        self._stashed_readings.append(value)

    def clear(self) -> None:
        self._stashed_readings.clear()

    @property
    def name(self) -> str:
        return self._name

    @property
    def parent(self) -> None:
        return None

    @property
    def model_info(self) -> ModelInfo:
        return self._model_info
