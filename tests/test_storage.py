"""Tests for SessionPathProvider and FileStoragePresenter."""

from __future__ import annotations

import datetime
from itertools import count
from typing import TYPE_CHECKING, Any

import numpy.typing as npt
import pytest
from redsun.storage import DataWriter, SourceInfo

from redsun_mimir.presenter.storage import FileStoragePresenter
from redsun_mimir.storage import SessionPathProvider

if TYPE_CHECKING:
    from pathlib import Path, PurePath

# ---------------------------------------------------------------------------
# Minimal DataWriter stub
# ---------------------------------------------------------------------------


class _MockWriter(DataWriter):
    """Minimal in-memory DataWriter for testing."""

    def __init__(self) -> None:
        super().__init__()
        self._is_open = False
        self._sources: dict[str, SourceInfo] = {}
        self._path: PurePath | None = None
        self._written: dict[str, list[npt.NDArray[Any]]] = {}
        self._write_counter: count[int] = count(1)
        self.opened_count = 0
        self.closed_count = 0
        self.set_path_calls: list[PurePath] = []

    @property
    def is_open(self) -> bool:
        return self._is_open

    @property
    def sources(self) -> dict[str, SourceInfo]:
        return self._sources

    @property
    def file_extension(self) -> str:
        return "zarr"

    @property
    def mimetype(self) -> str:
        return "application/x-zarr"

    def set_store_path(self, path: PurePath) -> None:
        self._path = path
        self.set_path_calls.append(path)

    def is_path_set(self) -> bool:
        return self._path is not None

    def open(self) -> None:
        self._is_open = True
        self.opened_count += 1

    def register(self, datakey: str, info: SourceInfo) -> None:
        self._sources[datakey] = info

    def unregister(self, datakey: str) -> None:
        self._sources.pop(datakey, None)

    def write(self, datakey: str, data: npt.NDArray[Any]) -> None:
        self._written.setdefault(datakey, []).append(data)
        self._update_count(next(self._write_counter))

    def close(self) -> None:
        self._is_open = False
        self.closed_count += 1
        self._sources.clear()
        self._path = None


class _DeviceWithWriter:
    """Minimal device satisfying HasWriterLogic."""

    def __init__(self, writer: _MockWriter) -> None:
        self._writer = writer

    @property
    def writer(self) -> _MockWriter:
        return self._writer


# ---------------------------------------------------------------------------
# SessionPathProvider tests
# ---------------------------------------------------------------------------


class TestSessionPathProvider:
    def test_generates_path_under_base_dir(self, tmp_path: Path) -> None:
        pp = SessionPathProvider(base_dir=tmp_path, session="s1")
        result = pp("snap")
        assert result.is_relative_to(tmp_path)

    def test_path_contains_session_segment(self, tmp_path: Path) -> None:
        pp = SessionPathProvider(base_dir=tmp_path, session="mysession")
        result = pp("snap")
        assert "mysession" in str(result)

    def test_path_contains_date_segment(self, tmp_path: Path) -> None:
        today = datetime.datetime.now().strftime("%Y_%m_%d")
        pp = SessionPathProvider(base_dir=tmp_path, session="s")
        result = pp("snap")
        assert today in str(result)

    def test_counter_increments_per_key(self, tmp_path: Path) -> None:
        pp = SessionPathProvider(base_dir=tmp_path, session="s")
        first = pp("snap")
        second = pp("snap")
        assert first != second
        assert first.name.endswith("_00000")
        assert second.name.endswith("_00001")

    def test_counters_are_independent_per_key(self, tmp_path: Path) -> None:
        pp = SessionPathProvider(base_dir=tmp_path, session="s")
        snap0 = pp("snap")
        live0 = pp("live")
        snap1 = pp("snap")
        assert snap0.name.endswith("_00000")
        assert live0.name.endswith("_00000")
        assert snap1.name.endswith("_00001")

    def test_group_suffix_in_filename(self, tmp_path: Path) -> None:
        pp = SessionPathProvider(base_dir=tmp_path, session="s")
        result = pp("scan", group="cam")
        assert "cam" in result.name

    def test_group_and_no_group_counters_are_independent(self, tmp_path: Path) -> None:
        pp = SessionPathProvider(base_dir=tmp_path, session="s")
        a = pp("scan")
        b = pp("scan", group="cam")
        assert a.name.endswith("_00000")
        assert b.name.endswith("_00000")

    def test_session_setter_resets_counters(self, tmp_path: Path) -> None:
        pp = SessionPathProvider(base_dir=tmp_path, session="s1")
        pp("snap")
        pp("snap")
        pp.session = "s2"
        result = pp("snap")
        assert result.name.endswith("_00000")

    def test_base_dir_setter_resets_counters(self, tmp_path: Path) -> None:
        pp = SessionPathProvider(base_dir=tmp_path / "a", session="s")
        pp("snap")
        pp.base_dir = tmp_path / "b"
        result = pp("snap")
        assert result.name.endswith("_00000")

    def test_base_dir_setter_updates_path(self, tmp_path: Path) -> None:
        pp = SessionPathProvider(base_dir=tmp_path / "a", session="s")
        pp.base_dir = tmp_path / "b"
        result = pp("snap")
        assert str(tmp_path / "b") in str(result)

    def test_directory_created_on_call(self, tmp_path: Path) -> None:
        pp = SessionPathProvider(base_dir=tmp_path, session="newsession")
        result = pp("snap")
        assert result.parent.is_dir()

    def test_scans_existing_directories(self, tmp_path: Path) -> None:
        SessionPathProvider(base_dir=tmp_path, session="s")
        date = datetime.datetime.now().strftime("%Y_%m_%d")
        existing = tmp_path / "s" / date
        existing.mkdir(parents=True)
        (existing / "snap_00000").mkdir()
        (existing / "snap_00001").mkdir()
        # Re-create provider so it scans
        pp2 = SessionPathProvider(base_dir=tmp_path, session="s")
        result = pp2("snap")
        assert result.name.endswith("_00002")

    def test_none_key_maps_to_default(self, tmp_path: Path) -> None:
        pp = SessionPathProvider(base_dir=tmp_path, session="s")
        result = pp(None)
        assert "default" in result.name


# ---------------------------------------------------------------------------
# FileStoragePresenter tests
# ---------------------------------------------------------------------------


class TestFileStoragePresenter:
    @pytest.fixture
    def writer(self) -> _MockWriter:
        return _MockWriter()

    @pytest.fixture
    def device(self, writer: _MockWriter) -> _DeviceWithWriter:
        return _DeviceWithWriter(writer)

    @pytest.fixture
    def presenter(
        self, tmp_path: Path, writer: _MockWriter, device: _DeviceWithWriter
    ) -> FileStoragePresenter:
        p = FileStoragePresenter(
            "storage_ctrl",
            {"cam": device},
        )
        p._path_provider = SessionPathProvider(base_dir=tmp_path, session="test")
        return p

    def test_available_writers_discovered(
        self, presenter: FileStoragePresenter, writer: _MockWriter
    ) -> None:
        """get_available_writers discovers the mock device's writer."""
        assert "application/x-zarr" in presenter.available_writers
        writers = presenter.available_writers["application/x-zarr"]
        assert writer in writers.values()

    def test_prepare_writers_sets_store_path(
        self,
        presenter: FileStoragePresenter,
        writer: _MockWriter,
    ) -> None:
        """_prepare_writers calls set_store_path on every registered writer."""
        presenter._prepare_writers("snap")
        assert len(writer.set_path_calls) == 1

    def test_prepare_writers_path_contains_plan_name(
        self,
        presenter: FileStoragePresenter,
        writer: _MockWriter,
    ) -> None:
        """Path generated by _prepare_writers includes the plan name."""
        presenter._prepare_writers("live_count")
        assert "live_count" in str(writer.set_path_calls[0])

    def test_prepare_writers_consecutive_runs_use_different_paths(
        self,
        presenter: FileStoragePresenter,
        writer: _MockWriter,
    ) -> None:
        """Two plan runs receive distinct store paths."""
        presenter._prepare_writers("snap")
        presenter._prepare_writers("snap")
        assert writer.set_path_calls[0] != writer.set_path_calls[1]

    def test_close_writers_calls_close(
        self,
        presenter: FileStoragePresenter,
        writer: _MockWriter,
    ) -> None:
        """_close_writers calls close() on every registered writer."""
        writer.open()
        presenter._close_writers()
        assert writer.closed_count == 1

    def test_close_writers_skips_when_none_registered(self, tmp_path: Path) -> None:
        """_close_writers is a no-op when no writers are available."""
        p = FileStoragePresenter("ctrl", {})
        p._close_writers()  # must not raise

    def test_refresh_path_provider_updates_base_dir(
        self,
        presenter: FileStoragePresenter,
        writer: _MockWriter,
        tmp_path: Path,
    ) -> None:
        """_refresh_path_provider changes where paths are generated."""
        new_dir = tmp_path / "new_root"
        presenter._refresh_path_provider(str(new_dir))
        presenter._prepare_writers("snap")
        assert str(new_dir) in str(writer.set_path_calls[0])

    def test_descriptor_callback_does_not_raise(
        self, presenter: FileStoragePresenter
    ) -> None:
        """descriptor() handles a config doc with no matching devices gracefully."""
        doc: Any = {
            "uid": "d-1",
            "name": "primary",
            "run_start": "r-1",
            "data_keys": {},
            "time": 0.0,
            "configuration": {},
            "hints": {},
            "object_keys": {},
        }
        presenter.descriptor(doc)  # must not raise
