from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import numpy as np
from bluesky.protocols import Reading, Triggerable
from redsun.engine import Status
from redsun.log import Loggable
from redsun.storage import DeviceStorageInfo, PrepareInfo, make_writer
from redsun.utils.descriptors import make_key

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
    describe_target: str, optional
        The property suffix to look for in the reader's ``describe()`` output.
        Combined with the reader name via ``make_key`` to form
        ``{reader.name}-{describe_target}``. Defaults to ``"buffer"``.
    collect_target: str, optional
        The stream key suffix to look for in the reader's ``describe_collect()``
        output.  Combined as ``{reader.name}:{collect_target}``.
        Defaults to ``"buffer:stream"``.
    """

    def __init__(
        self,
        reader: ReadableFlyer,
        describe: dict[str, Descriptor],
        collect: dict[str, Descriptor] | dict[str, dict[str, Descriptor]],
        describe_target: str = "buffer",
        collect_target: str = "buffer_stream",
    ) -> None:
        self._name = f"{reader.name}_median"
        self._reader_shape = reader.sensor_shape
        self._reader_storage_info = reader.storage_info()
        # Configuration/event keys use the {name}-{property} convention
        # (produced by make_key) so that event-document parsers splitting on "-"
        # can correctly extract the device name and property hint.
        self._describe_target_key = make_key(reader.name, describe_target)
        self._reading_key = make_key(self.name, describe_target)

        # Streaming keys keep the {name}-{signal} convention used by
        # describe_collect / collect_asset_docs / Writer.update_source.
        self._collect_target_key = make_key(reader.name, collect_target)
        self._collect_key = make_key(self.name, collect_target)
        self._valid_readings = False
        self._median: dict[str, Reading[Any]] = {}
        self._assets_collected: bool = False
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

        # initialize the cache with empty lists
        self._cache: list[npt.NDArray[np.generic]] = []

        self._empty_median = np.zeros(self._reader_shape, dtype=np.float32)

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

        If no valid readings are available, a dictionary with
        an empty array with the same size as the reference reader.
        """
        if not self._valid_readings:
            # return an empty dict
            return {
                self._reading_key: {
                    "value": self._empty_median,
                    "timestamp": time.time(),
                }
            }

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

    def storage_info(self) -> DeviceStorageInfo:
        """Delegate storage capability to the backing reader."""
        return self._reader_storage_info

    def trigger(self) -> Status:
        """Compute the median of the cached readings."""
        s = Status()
        if self._cache and not self._valid_readings:
            stack = np.stack(self._cache, axis=0)
            median_value: npt.NDArray[np.generic] = np.median(stack, axis=0)
            shape = median_value.shape
            dtype = median_value.dtype
            self._median[self._reading_key] = {
                "value": median_value,
                "timestamp": time.time(),
            }
            self._median_shape = shape
            self._median_dtype = dtype
            self._valid_readings = True
        s.set_finished()
        return s

    def prepare(self, value: PrepareInfo) -> Status:
        """Prepare for flight by constructing a writer from the shared StorageInfo."""
        s = Status()
        if not self._valid_readings:
            s.set_finished()
            return s
        try:
            storage = value.storage
            storage.devices[self.name] = self.storage_info()
            self._writer = make_writer(storage.uri, self.storage_info().mimetype)
            self._writer.update_source(
                self.name,
                self._collect_key,
                shape=self._median_shape,
                dtype=self._median_dtype,
            )
            self._sink = self._writer.prepare(self.name, capacity=1)
        except Exception as e:
            s.set_exception(e)
        else:
            s.set_finished()
        return s

    def kickoff(self) -> Status:
        """Start flying — write the single median frame to disk."""
        s = Status()
        if self._valid_readings:
            self._assets_collected = False
            self._writer.kickoff()
            self._sink.write(self._median[self._reading_key]["value"])
        s.set_finished()
        return s

    def complete(self) -> Status:
        """Complete — close the frame sink."""
        s = Status()
        if self._valid_readings:
            self._sink.close()
        s.set_finished()
        return s

    def collect_asset_docs(self, index: int | None = None) -> Iterator[StreamAsset]:
        if not self._valid_readings:
            return

        if self._assets_collected:
            return

        frames_written = self._writer.get_indices_written(self.name)
        if frames_written == 0:
            return

        frames_to_report = (
            min(index, frames_written) if index is not None else frames_written
        )

        self._assets_collected = True
        yield from self._writer.collect_stream_docs(self.name, frames_to_report)

    def get_index(self) -> int:
        if not self._valid_readings or not hasattr(self, "_writer"):
            return 0
        return self._writer.get_indices_written(self.name)

    @property
    def name(self) -> str:
        """The name of the pseudo model."""
        return self._name

    @property
    def parent(self) -> None:
        """The parent model, which is None for pseudo models."""
        return None
