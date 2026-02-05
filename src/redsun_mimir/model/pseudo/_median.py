from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import numpy as np
from bluesky.protocols import Readable, Triggerable
from bluesky.run_engine import call_in_bluesky_event_loop
from bluesky.utils import maybe_await
from sunflare.engine import Status

from redsun_mimir.protocols import HasCache

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bluesky.protocols import Descriptor, Reading


class MedianPseudoModel(Readable[Any], Triggerable, HasCache):
    """A pseudo-model representing a median processor.

    The pseudo-model is intended to be created inside a plan before
    the run is opened.

    Parameters
    ----------
    readers: Sequence[Readable[Any]]
        The list of reader objects whose readings will be used
        to compute the median.
    target: str, optional
        The target key substring to look for in the detector readings.
    """

    def __init__(
        self, readers: Sequence[Readable[Any]], target: str = "buffer"
    ) -> None:
        async def describe_inner(
            readers: Sequence[Readable[Any]],
        ) -> list[dict[str, Descriptor]]:
            return [await maybe_await(det.describe()) for det in readers]

        self._name = "PSEUDO:median"
        self._valid_readings = False
        self._readings: dict[str, Reading[Any]] = {}
        descriptor_list = call_in_bluesky_event_loop(describe_inner(readers))
        # modify the descriptor keys in-place by changing the names
        # from whatever they were to include a '[median]' suffix
        self._keys_to_watch: list[str] = []
        for desc in descriptor_list:
            for key in list(desc.keys()):
                if target in key:
                    self._keys_to_watch.append(key)
                    new_key = f"{key}[median]"
                    desc[new_key] = desc.pop(key)
                    desc[new_key]["source"] = "median-computed"
                else:
                    # remove other keys
                    desc.pop(key)

        # merge all descriptors into one
        self._descriptor: dict[str, Descriptor] = {}
        for desc in descriptor_list:
            self._descriptor.update(desc)

        # initialize the cache with empty lists
        self._cache: dict[str, list[dict[str, Reading[Any]]]] = {
            det.name: [] for det in readers
        }

    def describe(self) -> dict[str, Descriptor]:
        """Return the descriptor for the median pseudo model."""
        return self._descriptor

    def read(self) -> dict[str, Reading[Any]]:
        """Read the current value of the pseudo model.

        If no valid readings are available, returns an empty dictionary.
        """
        if not self._valid_readings:
            # return an empty dict
            return {}

        return self._readings

    def stash(self, name: str, values: dict[str, Reading[Any]]) -> Status:
        """Store readings in the cache."""
        s = Status()
        # find the keys to watch and store only those readings
        self._cache.setdefault(name, [])
        self._cache[name].append(values)
        s.set_finished()
        return s

    def clear(self) -> Status:
        """Clear the cached readings."""
        s = Status()
        self._cache.clear()
        self._valid_readings = False
        s.set_finished()
        return s

    def trigger(self) -> Status:
        """Compute the median of the cached readings."""
        s = Status()
        # for each device key in the cache, compute the median
        # and store each median reading in self._readings with
        # the key being the reading key with the [median] suffix
        for readings_list in self._cache.values():
            if not readings_list:
                continue
            # for each key in the readings, compute the median
            keys = readings_list[0].keys()
            for key in keys:
                values = [
                    reading_set[key]["value"]
                    for reading_set in readings_list
                    if key in reading_set
                ]
                if not values:
                    continue
                median_value = np.median(values)
                self._readings[f"{key}[median]"] = {
                    "value": median_value,
                    "timestamp": time.time(),
                }
        self._valid_readings = True
        return s

    @property
    def name(self) -> str:
        """The name of the pseudo model."""
        return self._name

    @property
    def parent(self) -> None:
        """The parent model, which is None for pseudo models."""
        return None
