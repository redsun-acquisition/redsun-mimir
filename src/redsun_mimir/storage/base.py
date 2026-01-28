from __future__ import annotations

import threading as th
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar, TypeVar

from sunflare.log import Loggable

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    import numpy as np
    import numpy.typing as npt
    from bluesky.protocols import Descriptor, StreamAsset
    from event_model.documents import StreamDatum, StreamResource


@dataclass
class SourceInfo:
    """Metadata for a registered data source."""

    name: str
    dtype: np.dtype[Any]
    shape: tuple[int, ...]
    data_key: str
    mimetype: str = "application/octet-stream"
    frames_written: int = 0
    collection_counter: int = 0
    stream_resource_uid: str = field(default_factory=lambda: str(uuid.uuid4()))


# Type variable for subclass registry pattern
_W = TypeVar("_W", bound="WriterBase")


class WriterBase(ABC, Loggable):
    """Abstract base class for detector data writers.

    This class provides common functionality for writing detector data to
    external storage backends (Zarr, HDF5, TIFF, etc.). It follows the
    ophyd-async DetectorWriter pattern:

    - Writers are internal helpers, NOT bluesky devices
    - The detector (camera) is the bluesky device
    - The detector calls writer methods directly

    **Lifecycle** (called by the detector):

    1. ``register_source()``: Register data sources (cameras) before opening
    2. ``open()``: Open storage file and create datasets for all sources
    3. ``submit_frame()``: Queue frames for writing (per source)
    4. ``get_indices_written()``: Query current write progress (per source)
    5. ``collect_stream_docs()``: Get asset documents for emission (per source)
    6. ``close()``: Finalize and close the storage file

    **Multi-source Support**:

    Writers support multiple data sources (cameras) writing to the same file.
    Each source is registered before ``open()`` and identified by a unique name.

    **Multiton Pattern**:

    Use the class method ``get()`` to obtain shared writer instances:

    - ``MyWriter.get(name)`` returns an existing writer or creates one
    - Multiple detectors can share the same writer by using the same name

    Parameters
    ----------
    name : str
        Name of this writer (used for logging and registry lookup).

    Notes
    -----
    Subclasses must implement:
    - ``open()``: Create backend-specific storage
    - ``close()``: Close backend-specific storage
    - ``_write_frame()``: Write a frame to backend storage
    - ``_get_mimetype()``: Return the MIME type for StreamResource documents
    """

    # Class-level registry of writer instances by name
    # Each subclass gets its own registry via __init_subclass__
    _instances: ClassVar[dict[str, Any]] = {}
    _registry_lock: ClassVar[th.Lock] = th.Lock()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Initialize subclass with its own registry."""
        super().__init_subclass__(**kwargs)
        cls._instances = {}
        cls._registry_lock = th.Lock()

    @classmethod
    def get(cls: type[_W], name: str) -> _W:
        """Get or create a writer instance by name.

        This implements a multiton pattern: each unique name gets exactly
        one writer instance, shared across all callers.

        Parameters
        ----------
        name : str
            Unique identifier for the writer.

        Returns
        -------
        WriterBase
            The writer instance (existing or newly created).

        Example
        -------
        ::

            # First call creates the writer
            writer = ZarrWriter.get("scan_writer")

            # Subsequent calls return the same instance
            same_writer = ZarrWriter.get("scan_writer")
            assert writer is same_writer
        """
        with cls._registry_lock:
            if name not in cls._instances:
                cls._instances[name] = cls(name)
            return cls._instances[name]

    @classmethod
    def remove(cls, name: str) -> None:
        """Remove a writer from the registry.

        Call this after ``close()`` when the writer is no longer needed.
        Does nothing if the name is not registered.

        Parameters
        ----------
        name : str
            The writer name to remove.
        """
        with cls._registry_lock:
            cls._instances.pop(name, None)

    @classmethod
    def clear_all(cls) -> None:
        """Close and remove all registered writers.

        Useful for cleanup in tests or application shutdown.
        """
        with cls._registry_lock:
            for writer in cls._instances.values():
                writer.close()
            cls._instances.clear()

    def __init__(self, name: str) -> None:
        self._name = name
        self._store_path: str = ""
        self._capacity: int = 0

        # Multi-source tracking: name -> SourceInfo
        self._sources: dict[str, SourceInfo] = {}

        # Thread safety
        self._lock = th.Lock()
        self._is_open: bool = False

    @property
    def name(self) -> str:
        """Return the name of this writer."""
        return self._name

    @property
    def is_open(self) -> bool:
        """Return whether the writer is currently open."""
        return self._is_open

    @property
    def sources(self) -> dict[str, SourceInfo]:
        """Return the registered sources (read-only view)."""
        return self._sources

    def update_source(
        self,
        name: str,
        dtype: Any,
        shape: tuple[int, ...],
    ) -> None:
        """Register or update a data source (camera) with the writer.

        Can be called multiple times to update dtype/shape before ``open()``.
        Each source will get its own dataset/array in the storage file.

        Parameters
        ----------
        name : str
            Unique identifier for the data source.
        dtype
            Data type (backend-specific, e.g., DataType from acquire_zarr).
        shape : tuple[int, ...]
            Shape of a single frame (height, width).

        Raises
        ------
        RuntimeError
            If called after ``open()``.
        """
        if self._is_open:
            raise RuntimeError(
                "Cannot update sources after open(). Call close() first."
            )

        data_key = f"{name}:buffer:stream"
        self._sources[name] = SourceInfo(
            name=name,
            dtype=dtype,
            shape=shape,
            data_key=data_key,
            mimetype=self._get_mimetype(),
        )
        self.logger.debug(f"Updated source '{name}' with shape {shape}")

    def unregister_source(self, name: str) -> None:
        """Unregister a data source.

        Parameters
        ----------
        name : str
            The source identifier to remove.

        Raises
        ------
        RuntimeError
            If called while the writer is open.
        """
        if self._is_open:
            raise RuntimeError("Cannot unregister sources while open.")

        self._sources.pop(name, None)

    @abstractmethod
    def open(
        self,
        *,
        store_path: str | Path,
        capacity: int = 0,
    ) -> dict[str, Descriptor]:
        """Open storage and create datasets for all registered sources.

        Subclasses must implement this to create backend-specific storage.

        Parameters
        ----------
        store_path : str | Path
            Path to storage file/directory.
        capacity : int
            Maximum frames per source (0 for unlimited).

        Returns
        -------
        dict[str, Descriptor]
            Combined descriptor dict for all sources with ``external: "STREAM:"``.

        Raises
        ------
        RuntimeError
            If the writer is already open or no sources are registered.
        """
        ...

    @abstractmethod
    def close(self) -> None:
        """Close the storage file and finalize writing.

        Subclasses must implement this to close backend-specific storage.
        Should be safe to call multiple times.
        """
        ...

    @abstractmethod
    def _write_frame(self, name: str, frame: npt.NDArray[np.generic]) -> None:
        """Write a frame to the backend storage.

        Subclasses must implement this for backend-specific frame writing.
        Called by ``submit_frame()`` while holding the lock.

        Parameters
        ----------
        name : str
            Source name.
        frame : np.ndarray
            Frame data to write.
        """
        ...

    @abstractmethod
    def _get_mimetype(self) -> str:
        """Return the MIME type for StreamResource documents.

        Subclasses must implement this to return the appropriate MIME type
        for their storage format.

        Returns
        -------
        str
            MIME type string (e.g., "application/x-zarr", "application/x-hdf5").
        """
        ...

    def _prepare_open(self, store_path: str | Path, capacity: int) -> None:
        """Prepare for opening storage.

        Call this at the start of ``open()`` implementations.

        Parameters
        ----------
        store_path : str | Path
            Path to storage file/directory.
        capacity : int
            Maximum frames per source.

        Raises
        ------
        RuntimeError
            If the writer is already open or no sources are registered.
        """
        if self._is_open:
            raise RuntimeError("Writer is already open. Call close() first.")

        if not self._sources:
            raise RuntimeError("No sources registered. Call register_source() first.")

        self._store_path = str(store_path)
        self._capacity = capacity

        # Reset all source counters and generate fresh UIDs
        for source in self._sources.values():
            source.frames_written = 0
            source.collection_counter = 0
            source.stream_resource_uid = str(uuid.uuid4())

    def _build_descriptors(self) -> dict[str, Descriptor]:
        """Build descriptor dict for all registered sources.

        Call this at the end of ``open()`` implementations.

        Returns
        -------
        dict[str, Descriptor]
            Combined descriptor dict for all sources.
        """
        descriptors: dict[str, Descriptor] = {}
        for source in self._sources.values():
            descriptors[source.data_key] = {
                "source": "data",
                "dtype": "array",
                "shape": [None, *source.shape],
                "external": "STREAM:",
            }
        return descriptors

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

        # Emit StreamResource only on first call for this source
        if source.collection_counter == 0:
            stream_resource: StreamResource = {
                "data_key": source.data_key,
                "mimetype": source.mimetype,
                "parameters": {"array_name": source.name},
                "uid": source.stream_resource_uid,
                "uri": self._store_path,
            }
            yield ("stream_resource", stream_resource)

        # Emit StreamDatum with incremental indices
        stream_datum: StreamDatum = {
            "descriptor": "",  # RunEngine fills this
            "indices": {"start": source.collection_counter, "stop": frames_to_report},
            "seq_nums": {"start": 0, "stop": 0},  # RunEngine fills this
            "stream_resource": source.stream_resource_uid,
            "uid": f"{source.stream_resource_uid}/{source.collection_counter}",
        }
        yield ("stream_datum", stream_datum)

        source.collection_counter = frames_to_report

    def submit_frame(self, name: str, frame: npt.NDArray[np.generic]) -> None:
        """Submit a frame for writing.

        Thread-safe: multiple cameras can submit frames concurrently.

        Parameters
        ----------
        name : str
            Source name (passed to ``register_source()``).
        frame : np.ndarray
            Frame data to write.

        Raises
        ------
        RuntimeError
            If called before ``open()`` or after ``close()``.
        KeyError
            If the source name is not registered.
        """
        if not self._is_open:
            raise RuntimeError("Writer is not open. Call open() first.")

        if name not in self._sources:
            raise KeyError(f"Unknown source '{name}'")

        source = self._sources[name]

        with self._lock:
            self._write_frame(name, frame)
            source.frames_written += 1

    def reset_collection_state(self, name: str | None = None) -> None:
        """Reset the collection counter for a new acquisition.

        Parameters
        ----------
        name : str | None
            Source name to reset. If None, resets all sources.
        """
        if name is None:
            for source in self._sources.values():
                source.collection_counter = 0
                source.stream_resource_uid = str(uuid.uuid4())
        elif name in self._sources:
            source = self._sources[name]
            source.collection_counter = 0
            source.stream_resource_uid = str(uuid.uuid4())
