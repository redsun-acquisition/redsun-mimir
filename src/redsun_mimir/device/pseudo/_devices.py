from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, TypedDict

import numpy as np
from bluesky.protocols import Reading, Triggerable
from sunflare.engine import Status
from sunflare.log import Loggable
from sunflare.storage import StorageDescriptor

from redsun_mimir.protocols import PseudoCacheFlyer, ReadableFlyer

if TYPE_CHECKING:
    from typing import Iterator

    import numpy.typing as npt
    from bluesky.protocols import Descriptor, Reading, StreamAsset
    from typing_extensions import TypeIs


def is_flat_descriptor(
    d: dict[str, Descriptor] | dict[str, dict[str, Descriptor]],
) -> TypeIs[dict[str, Descriptor]]:
    """Check if the given descriptor dictionary is flat."""
    first_value = next(iter(d.values()))
    has_descriptor_keys = isinstance(first_value, dict) and all(
        key in first_value for key in ("source", "dtype", "shape")
    )
    return has_descriptor_keys


class PrepareKwargs(TypedDict):
    """Keyword arguments for the `prepare` method of the `MedianPseudoDevice`."""


class MedianPseudoDevice(PseudoCacheFlyer, Triggerable, Loggable):
    """A pseudo-model representing a median processor.

    The pseudo-model is intended to be created inside a plan before
    the run is opened. There should be one instance of
    the pseudo-model per each detector that is being monitored for median computation.

    Parameters
    ----------
    reader: ReadableFlyer
        Reader object used to pull readings over which the median will be computed.
        It must implement both the `Readable` and `Flyer` protocols.
    target: str, optional
        The target key substring to look for in the detector readings.
    """

    storage = StorageDescriptor()

    def __init__(
        self,
        reader: ReadableFlyer,
        describe: dict[str, Descriptor],
        collect: dict[str, Descriptor] | dict[str, dict[str, Descriptor]],
        describe_target: str = "buffer",
        collect_target: str = "buffer:stream",
    ) -> None:
        self._name = f"{reader.name}_median"
        self._describe_target_key = f"{reader.name}:{describe_target}"
        self._collect_target_key = f"{reader.name}:{collect_target}"
        self._reading_key = f"{self.name}:{describe_target}"
        self._collect_key = f"{self.name}:{collect_target}"
        self._valid_readings = False
        self._median: dict[str, Reading[Any]] = {}
        describe_descriptor = describe
        collect_descriptor: dict[str, Descriptor] = {}

        if is_flat_descriptor(collect):
            collect_descriptor = collect
        else:
            collect_descriptor = collect[self._collect_target_key]

        self._describe_descriptor = {
            key.replace(self._describe_target_key, self._reading_key): value
            for key, value in describe_descriptor.items()
            if self._describe_target_key in key
        }
        self._collect_descriptor = {
            key.replace(self._collect_target_key, self._collect_key): value
            for key, value in collect_descriptor.items()
            if self._collect_target_key in key
        }

        old_describe_source = describe_descriptor[self._describe_target_key]["source"]
        new_describe_source = f"{old_describe_source}\\median"
        self._describe_descriptor[self._reading_key]["source"] = new_describe_source

        old_collect_source = collect_descriptor[self._collect_target_key]["source"]
        new_collect_source = f"{old_collect_source}\\median"
        self._collect_descriptor[self._collect_key]["source"] = new_collect_source

        # initialize the cache with empty lists
        self._cache: list[npt.NDArray[np.generic]] = []

    def describe_configuration(self) -> dict[str, Descriptor]:
        """Return the configuration descriptor.

        Since the median pseudo model does not have any configuration parameters,
        returns an empty dictionary.
        """
        return {}

    def describe(self) -> dict[str, Descriptor]:
        """Return the descriptor for the median pseudo model."""
        return self._describe_descriptor

    def describe_collect(self) -> dict[str, Descriptor]:
        """Return the collect descriptor for the median pseudo model."""
        return self._collect_descriptor

    def read_configuration(self) -> dict[str, Reading[Any]]:
        """Return the current configuration readings.

        Since the median pseudo model does not have any configuration parameters,
        returns an empty dictionary.
        """
        return {}

    def read(self) -> dict[str, Reading[Any]]:
        """Read the current value of the pseudo model.

        If no valid readings are available, returns an empty dictionary.
        """
        if not self._valid_readings:
            # return an empty dict
            return {}

        return self._median

    def stash(self, value: dict[str, Reading[Any]]) -> Status:
        """Store readings in the cache."""
        s = Status()
        self._cache.append(value[self._describe_target_key]["value"])
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
        # compute the median for the target key and store it in the _median dict
        if self._cache:
            median_value: npt.NDArray[np.generic] = np.median(
                np.stack(self._cache, axis=0), axis=0
            )
            shape = median_value.shape
            dtype = median_value.dtype
            if self.storage is not None:
                self.storage.update_source(self.name, dtype, shape)
            median_key = self._describe_target_key.replace(
                self._describe_target_key, self._reading_key
            )
            self._median[median_key] = {"value": median_value, "timestamp": time.time()}
            self._valid_readings = True
        s.set_finished()
        return s

    def prepare(self, value: PrepareKwargs) -> Status:
        """Prepare the pseudo model for flight by writing the median readings to disk."""
        s = Status()
        if self._valid_readings and self.storage is not None:
            self.logger.debug(f"Valid median for {self.name}, preparing for flight.")
            self._sink = self.storage.prepare(self.name, capacity=1)
        s.set_finished()
        return s

    def kickoff(self) -> Status:
        """Start flying.

        Writes the single median reading to disk;
        it does not imply the existance of a data stream,
        but for consistency with other flyers, this method is provided.
        """
        s = Status()
        if self._valid_readings:
            self._sink.write(self._median[self._reading_key]["value"])
        s.set_finished()
        return s

    def complete(self) -> Status:
        """Complete the flying process.

        Tells the writer that no more data will be sent for this pseudo model;
        this will close the frame sink.
        """
        s = Status()
        if self._valid_readings:
            self._sink.close()
        s.set_finished()
        return s

    def collect_asset_docs(self, index: int | None = None) -> Iterator[StreamAsset]:
        if not self._valid_readings or self.storage is None:
            return

        frames_written = self.storage.get_indices_written(self.name)
        if frames_written == 0:
            return

        # Determine how many frames to report
        frames_to_report = min(index, frames_written) if index else frames_written

        # Delegate to writer
        yield from self.storage.collect_stream_docs(self.name, frames_to_report)

    def get_index(self) -> int:
        if not self._valid_readings or self.storage is None:
            return 0
        return self.storage.get_indices_written(self.name)

    @property
    def name(self) -> str:
        """The name of the pseudo model."""
        return self._name

    @property
    def parent(self) -> None:
        """The parent model, which is None for pseudo models."""
        return None
