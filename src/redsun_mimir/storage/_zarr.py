from __future__ import annotations

from typing import TYPE_CHECKING

from acquire_zarr import (
    ArraySettings,
    Dimension,
    DimensionType,
    StreamSettings,
    ZarrStream,
)

from .base import WriterBase

if TYPE_CHECKING:
    from pathlib import Path

    import numpy as np
    import numpy.typing as npt
    from bluesky.protocols import Descriptor


class ZarrWriter(WriterBase):
    """Zarr-based implementation of WriterBase.

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
    ::

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
        self._stream: ZarrStream | None = None
        self._stream_settings = StreamSettings()

    def _get_mimetype(self) -> str:
        """Return the MIME type for Zarr storage."""
        return "application/x-zarr"

    def open(
        self,
        *,
        store_path: str | Path,
        capacity: int = 0,
    ) -> dict[str, Descriptor]:
        """Open Zarr storage and prepare for writing frames.

        Creates arrays for all registered sources.

        Parameters
        ----------
        store_path : str | Path
            Path to the Zarr store directory.
        capacity : int
            Maximum number of frames per source (0 for unlimited).

        Returns
        -------
        dict[str, Descriptor]
            Combined descriptor dict for all sources.
        """
        # Common validation and setup
        self._prepare_open(store_path, capacity)

        # Create ArraySettings for each source
        array_settings_list: list[ArraySettings] = []
        for source in self._sources.values():
            height, width = source.shape
            t = Dimension(
                name="t",
                kind=DimensionType.TIME,
                array_size_px=self._capacity,  # 0 = unlimited
                chunk_size_px=1,
                shard_size_chunks=2,
            )
            y = Dimension(
                name="y",
                kind=DimensionType.SPACE,
                array_size_px=height,
                chunk_size_px=max(1, height // 4),
                shard_size_chunks=2,
            )
            x = Dimension(
                name="x",
                kind=DimensionType.SPACE,
                array_size_px=width,
                chunk_size_px=max(1, width // 4),
                shard_size_chunks=2,
            )
            array_settings_list.append(
                ArraySettings(
                    dimensions=[t, y, x],
                    data_type=source.dtype,
                    output_key=source.name,
                )
            )

        self._stream_settings.store_path = self._store_path
        self._stream_settings.arrays = array_settings_list
        self._stream = ZarrStream(self._stream_settings)
        self._is_open = True

        self.logger.debug(
            f"Opened Zarr writer at {self._store_path} "
            f"with {len(self._sources)} source(s): {list(self._sources.keys())}"
        )

        return self._build_descriptors()

    def close(self) -> None:
        """Close the Zarr storage file and finalize writing.

        Safe to call multiple times.
        """
        with self._lock:
            if self._stream is not None:
                self._stream.close()
                self._stream = None
                total_frames = sum(s.frames_written for s in self._sources.values())
                self.logger.debug(
                    f"Closed Zarr writer ({total_frames} total frames "
                    f"across {len(self._sources)} source(s))"
                )
            self._is_open = False

    def _write_frame(self, name: str, frame: npt.NDArray[np.generic]) -> None:
        """Write a frame to the Zarr stream.

        Parameters
        ----------
        name : str
            Source name.
        frame : np.ndarray
            Frame data to write.
        """
        if self._stream is None:
            raise RuntimeError("Stream is not initialized")
        # acquire-zarr uses output_key to route to the correct array
        self._stream.append(frame, key=name)
