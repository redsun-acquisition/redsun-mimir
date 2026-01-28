from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from acquire_zarr import (
    ArraySettings,
    Dimension,
    DimensionType,
    StreamSettings,
    ZarrStream,
)
from bluesky.protocols import Descriptor

from .base import Writer

if TYPE_CHECKING:
    from pathlib import Path

    import numpy as np
    import numpy.typing as npt
    from bluesky.protocols import Descriptor

    from redsun_mimir.storage.base import SinkGenerator


class ZarrWriter(Writer):
    """Zarr-based implementation of a Writer.

    This class handles writing detector frames to Zarr storage using
    the acquire-zarr library. It supports **multiple data sources**
    (cameras) writing to the same Zarr store, each as a separate array.

    Use the class method ``get()`` to obtain shared writer instances:

    - ``ZarrWriter.get(name)`` returns an existing writer or creates one
    - Multiple detectors can share the same writer by using the same name

    Parameters
    ----------
    name : str
        Name of this writer (used for logging and registry lookup).

    Example
    -------

        # Get shared writer (creates if doesn't exist)
        writer = ZarrWriter.get("scan_writer")

        # Each camera updates its source info
        writer.update_source("camera1", DataType.UINT16, (512, 512))

        # Open the store
        writer.open(store_path="/data/scan001.zarr", capacity=100)

        # Submit frames
        writer.submit_frame("camera1", frame)

        # Collect docs
        yield from writer.collect_stream_docs(
            "camera1", writer.get_indices_written("camera1")
        )

        writer.close()
        ZarrWriter.remove("scan_writer")
    """

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._stream_settings = StreamSettings()
        self._dimensions: dict[str, list[Dimension]] = {}
        self._array_settings: dict[str, ArraySettings] = {}
        self._store_path_set: bool = False

    @property
    def mimetype(self) -> str:
        """Return the MIME type for Zarr storage."""
        return "application/x-zarr"

    def prepare(
        self, name: str, store_path: str | Path, capacity: int = 0
    ) -> tuple[SinkGenerator, dict[str, Descriptor]]:
        if not self._store_path_set:
            self._stream_settings.store_path = str(store_path)
            self._store_path_set = True

        source = self._sources[name]
        height, width = source.shape
        dimensions = [
            Dimension(
                name="t",
                kind=DimensionType.TIME,
                array_size_px=capacity,  # 0 = unlimited
                chunk_size_px=1,
                shard_size_chunks=2,
            ),
            Dimension(
                name="y",
                kind=DimensionType.SPACE,
                array_size_px=height,
                chunk_size_px=max(1, height // 4),
                shard_size_chunks=2,
            ),
            Dimension(
                name="x",
                kind=DimensionType.SPACE,
                array_size_px=width,
                chunk_size_px=max(1, width // 4),
                shard_size_chunks=2,
            ),
        ]
        self._dimensions[name] = dimensions
        self._array_settings[name] = ArraySettings(
            dimensions=dimensions,
            data_type=source.dtype,
            output_key=source.name,
        )

        return super().prepare(name, store_path, capacity)

    def kickoff(self) -> None:
        if self.is_open:
            return

        self._stream_settings.arrays = list(self._array_settings.values())
        self._stream = ZarrStream(self._stream_settings)

        return super().kickoff()

    def _finalize(self) -> None:
        self._stream.close()

    def _write_frame(self, name: str, frame: npt.NDArray[np.generic]) -> None:
        """Write a frame to the Zarr stream.

        Parameters
        ----------
        name : str
            Source name.
            Routes the zarr write to the correct chunk.
        frame : np.ndarray
            Frame data to write.
        """
        self._stream.append(frame, key=name)
