from __future__ import annotations

import abc
import threading as th
import uuid
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, TypeVar

from sunflare.log import Loggable

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator
    from pathlib import Path
    from typing import Any, ClassVar, TypeAlias

    import numpy as np
    import numpy.typing as npt
    from bluesky.protocols import StreamAsset
    from event_model.documents import StreamDatum, StreamResource
    from typing_extensions import Self

    SinkGenerator: TypeAlias = Generator[None, npt.NDArray[np.generic]]


@dataclass
class SourceInfo:
    """Metadata for a registered data source."""

    name: str
    dtype: np.dtype[np.generic]
    shape: tuple[int, ...]
    data_key: str
    mimetype: str = "application/octet-stream"
    frames_written: int = 0
    collection_counter: int = 0
    stream_resource_uid: str = field(default_factory=lambda: str(uuid.uuid4()))


_W = TypeVar("_W", bound="Writer")


class Writer(abc.ABC, Loggable):
    """Abstract base class for data writers.

    This interface loosely follows the Bluesky Flyable interface,
    while keeping it generic so not to rely on some protocols
    specifications (e.g. methods don't need to return a `Status` object);
    this is left to the specific detector object that uses the writer.

    It is intended to be used as a shared component by multiple detectors.

    To respect the Bluesky Flyable protocols, the call order is:

    - ``prepare()``: called by each detector to set up storage
    - ``kickoff()``: called once to open the storage backend
    - ``complete()``: called by each detector to finalize its acquisition

    It also provides the means to create a descriptor map to be returned
    from the detector's `describe_collect()` method, as well as
    generating the appropriate StreamResource and StreamDatum documents
    for `collect_asset_docs()`.

    Subclasses must implement specific storage backends via
    the following:

    - ``mimetype`` property: return the MIME type for this writer
    - ``prepare()`` method: prepare storage for a data source
    - ``_write_frame()`` method: private method to write a frame to storage
    - ``_finalize()`` method: private method to close the storage backend

    Parameters
    ----------
    name : str
        Name of this writer (used for logging and registry lookup).

    Attributes
    ----------
    is_open : bool
        Return whether the writer is currently open.

    Notes
    -----
    Detectors can push frames to the writer via the frame sink
    returned by the `prepare()` method (this is thread-safe);
    frames will be written in the order they are received and
    arranged by the storage backend so to keep track of the frames origin.
    """

    #: Registry of writer instances by name.
    _instances: ClassVar[dict[str, Self]] = {}

    #: Lock for thread-safe access to the registry.
    _registry_lock: ClassVar[th.Lock] = th.Lock()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Initialize subclass.

        Creates a separate registry for each subclass
        and a class-based lock for thread safety.
        """
        super().__init_subclass__(**kwargs)
        cls._instances = {}
        cls._registry_lock = th.Lock()

    @classmethod
    def get(cls: type[_W], name: str) -> _W:
        """Get or create a shared writer instance by name.

        Parameters
        ----------
        name : str
            Name of the writer instance.

        Returns
        -------
        Writer
            Shared writer instance.
        """
        with cls._registry_lock:
            if name not in cls._instances:
                cls._instances[name] = cls(name)
            return cls._instances[name]

    def __init__(self, name: str) -> None:
        self._name = name
        self._store_path = ""
        self._capacity = 0

        # per-instance lock for
        # thread safety with multiple
        # detectors using the same writer
        self._lock = th.Lock()

        # writer state
        self._is_open = False

        # per-writer source registry
        self._sources: dict[str, SourceInfo] = {}

        # active frame sinks mapped by source name
        self._frame_sinks: dict[
            str, Generator[None, npt.NDArray[np.generic], None]
        ] = {}

    @property
    def is_open(self) -> bool:
        """Return whether the writer is currently open."""
        return self._is_open

    @property
    def name(self) -> str:
        """Return the name of this writer."""
        return self._name

    @property
    @abc.abstractmethod
    def mimetype(self) -> str:
        """Return the MIME type for this writer."""
        ...

    @property
    def sources(self) -> MappingProxyType[str, SourceInfo]:
        """Return a read-only view of the registered data sources."""
        return MappingProxyType(self._sources)

    def update_source(
        self, name: str, dtype: np.dtype[np.generic], shape: tuple[int, ...]
    ) -> None:
        """Register or update a data source.

        A "source" is a detector requesting to write frames to the writer.
        If the source name already exists, its metadata is updated;
        otherwise, a new source entry is created.

        This should be called by detectors during their initialization.

        Parameters
        ----------
        name : str
            Name of the data source (e.g., detector.name).
        dtype : np.dtype
            NumPy data type of the source frames.
        shape : tuple[int, ...]
            Shape of individual frames from the source.

        Raises
        ------
        RuntimeError
            If the writer is currently open.
        """
        if self._is_open:
            raise RuntimeError("Cannot update sources while writer is open.")

        data_key = f"{name}:buffer:stream"
        self._sources[name] = SourceInfo(
            name=name,
            dtype=dtype,
            shape=shape,
            data_key=data_key,
            mimetype=self.mimetype,
        )
        self.logger.debug(f"Updated source '{name}' with shape {shape}")

    def clear_source(self, name: str, raise_if_missing: bool = False) -> None:
        """Remove a registered data source.

        Parameters
        ----------
        name : str
            Name of the data source to remove.
        raise_if_missing : bool, optional
            If True, raise KeyError if the source is not found.
            Default is False (exception is suppressed).

        Raises
        ------
        RuntimeError
            If the writer is currently open.
        KeyError
            If the source name is not registered
            and `raise_if_missing` is True.
        """
        if self._is_open:
            raise RuntimeError("Cannot clear sources while writer is open.")

        try:
            del self._sources[name]
            self.logger.debug(f"Cleared source '{name}'")
        except KeyError as e:
            self.logger.error(f"Source '{name}' not found to clear.")
            if raise_if_missing:
                raise e

    def get_indices_written(self, name: str | None = None) -> int:
        """Get the number of frames written for a source.

        Parameters
        ----------
        name : str | None
            Source name. If None, returns the minimum across all sources
            (useful for synchronization).

        Returns
        -------
        int
            Frames written for the source, or minimum across all sources.

        Raises
        ------
        KeyError
            If the source name is not registered.
        """
        if name is None:
            if not self._sources:
                return 0
            return min(s.frames_written for s in self._sources.values())

        if name not in self._sources:
            raise KeyError(f"Unknown source '{name}'")
        return self._sources[name].frames_written

    def reset_collection_state(self, name: str) -> None:
        """Reset the collection counter for a new acquisition.

        Parameters
        ----------
        name : str
            Source name to reset.
        """
        source = self._sources[name]
        source.collection_counter = 0
        source.stream_resource_uid = str(uuid.uuid4())

    def _create_frame_sink(self, name: str) -> SinkGenerator:
        """Return a generator function that sends frames to the storage writer."""
        if name not in self._sources:
            raise KeyError(f"Unknown source '{name}'")

        # Cache references to avoid repeated lookups in hot path
        source = self._sources[name]

        def _frame_sink() -> SinkGenerator:
            try:
                while True:
                    frame = yield
                    with self._lock:
                        self._write_frame(name, frame)
                        source.frames_written += 1
            except GeneratorExit:
                pass

        return _frame_sink()

    @abc.abstractmethod
    def kickoff(self) -> None:
        """Kick off the writer for a new acquisition.

        Subclass implementations may perform any necessary setup here.

        The first time this is called, the writer will do the necessary
        operations to open the storage backend.

        Subsequent calls to kickoff() must simply return if the writer
        is already open.
        """
        if not self._is_open:
            self._is_open = True

    @abc.abstractmethod
    def prepare(
        self, name: str, store_path: str | Path, capacity: int = 0
    ) -> SinkGenerator:
        """Prepare storage for writing frames from a specific detector.

        Initializes a generator with send-only interface for writing frames
        to the backend.

        A specific writer backend must implement this logic so to pre-declare
        the space and time dimensions for the data source.

        Called multiple times by different detectors that share this writer.
        Data sources must call this method in their respective "prepare()".

        Parameters
        ----------
        name : str
            Source name (not used here, but part of the interface).
        store_path : str | Path
            Path to storage file/directory.
        capacity : int
            Maximum frames per source (0 for unlimited).

        Returns
        -------
        SinkGenerator
            A primed frame sink generator for writing frames.
        """
        source = self._sources[name]
        source.frames_written = 0
        source.collection_counter = 0
        source.stream_resource_uid = str(uuid.uuid4())

        if name not in self._frame_sinks:
            sink = self._create_frame_sink(name)
            next(sink)
            self._frame_sinks[name] = sink

        return self._frame_sinks[name]

    def complete(self, name: str) -> None:
        """Mark the current collection as complete for a source.

        Called by the detector's `complete()` method to signify that
        it has finished collecting data for the current acquisition.

        Parameters
        ----------
        name : str
            Source name.
        """
        self._frame_sinks[name].close()
        del self._frame_sinks[name]
        if len(self._frame_sinks) == 0:
            self._finalize()
            self._is_open = False

    @abc.abstractmethod
    def _write_frame(self, name: str, frame: npt.NDArray[np.generic]) -> None:
        """Write a frame to the backend storage.

        Subclasses must implement this method using API-specific calls.
        Private method - use the frame sink returned by ``prepare()`` instead.

        Parameters
        ----------
        name : str
            Source name.
        frame : npt.NDArray[np.generic]
            Frame data to write; the dtype and shape
            are encapsulated in the source information pointed by `name`.
        """
        ...

    @abc.abstractmethod
    def _finalize(self) -> None:
        """Finalize writing and close the storage.

        Called when all detectors using this writer have completed their
        acquisitions (`complete()` called for all sources).

        Subclasses must implement this method to perform any necessary
        finalization steps for the specific backend.
        """
        ...

    def collect_stream_docs(
        self,
        name: str,
        indices_written: int,
    ) -> Iterator[StreamAsset]:
        """Generate StreamResource and StreamDatum documents for a source.

        Parameters
        ----------
        name : str
            Source name (the name passed to ``register_source()``).
        indices_written : int
            Number of frames to report.

        Yields
        ------
        StreamAsset
            Tuples of ("stream_resource", doc) or ("stream_datum", doc).

        Raises
        ------
        KeyError
            If the source name is not registered.
        """
        if name not in self._sources:
            raise KeyError(f"Unknown source '{name}'")

        source = self._sources[name]

        # Nothing to report if no frames written
        if indices_written == 0:
            return

        # Cap to actual frames written
        frames_to_report = min(indices_written, source.frames_written)

        # Already reported everything?
        if source.collection_counter >= frames_to_report:
            return

        # emit StreamResource only on first call for this source
        if source.collection_counter == 0:
            stream_resource: StreamResource = {
                "data_key": source.data_key,
                "mimetype": source.mimetype,
                "parameters": {"array_name": source.name},
                "uid": source.stream_resource_uid,
                "uri": self._store_path,
            }
            yield ("stream_resource", stream_resource)

        # emit StreamDatum with incremental indices
        stream_datum: StreamDatum = {
            "descriptor": "",  # RunEngine fills this
            "indices": {"start": source.collection_counter, "stop": frames_to_report},
            "seq_nums": {"start": 0, "stop": 0},  # RunEngine fills this
            "stream_resource": source.stream_resource_uid,
            "uid": f"{source.stream_resource_uid}/{source.collection_counter}",
        }
        yield ("stream_datum", stream_datum)

        source.collection_counter = frames_to_report
