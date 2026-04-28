"""Storage utilities for redsun-mimir.

Provides path management helpers that were previously part of the
``redsun.storage`` public API.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ophyd_async.core import PathInfo, PathProvider, soft_signal_rw
from redsun.aio import run_coro

if TYPE_CHECKING:
    from bluesky.protocols import Reading


class SessionPathProvider(PathProvider):
    """Session-scoped path provider with per-key auto-increment counters.

    Produces paths of the form::

        <base_dir>/<session>/<YYYY_MM_DD>/<key>[_<group>]_<counter>

    The date segment is fixed at construction time so that a session
    started just before midnight does not split its files across two
    date directories.

    Parameters
    ----------
    base_dir : Path | None
        Root directory for all output files.
        Defaults to ``~/redsun-storage``.
    session : str
        Session name, used as the second path segment.
        Defaults to ``"default"``.
    max_digits : int
        Zero-padding width for the counter.  Defaults to ``5``.
    """

    def __init__(
        self,
        base_dir: Path | None = None,
        session: str = "default",
        max_digits: int = 5,
    ) -> None:
        self._base_dir = (
            base_dir if base_dir is not None else Path.home() / "redsun-storage"
        )
        self.group: str | None = None
        self._session = session
        self._max_digits = max_digits
        self._date = datetime.datetime.now().strftime("%Y_%m_%d")

        self.base_dir_sig = soft_signal_rw(str, initial_value=str(self._base_dir))
        self.session_sig = soft_signal_rw(str, initial_value=self._session)

        async def _wire() -> None:
            self.base_dir_sig.subscribe_reading(
                lambda r: self._on_base_dir_changed(next(iter(r.values())))
            )
            self.session_sig.subscribe_reading(
                lambda r: self._on_session_changed(next(iter(r.values())))
            )

        run_coro(_wire())

        self._counters: dict[str, int] = self._scan_existing()

    def _on_base_dir_changed(self, reading: Reading[str]) -> None:
        new = Path(reading["value"])
        if new != self._base_dir:
            self._base_dir = new
            self._counters = self._scan_existing()

    def _on_session_changed(self, reading: Reading[str]) -> None:
        if reading["value"] != self._session:
            self._session = reading["value"]
            self._counters = self._scan_existing()

    @property
    def session(self) -> str:
        """The active session name."""
        return self._session

    @session.setter
    def session(self, value: str) -> None:
        self._session = value
        self._counters = self._scan_existing()

    @property
    def base_dir(self) -> Path:
        """The root output directory."""
        return self._base_dir

    @base_dir.setter
    def base_dir(self, value: Path) -> None:
        self._base_dir = value
        self._counters = self._scan_existing()

    def _scan_existing(self) -> dict[str, int]:
        """Scan the current date directory and initialise counters from existing entries."""
        directory = self._base_dir / self._session / self._date
        counters: dict[str, int] = {}
        if not directory.is_dir():
            return counters
        for entry in directory.iterdir():
            # strips last suffix: camera_00000.zarr → camera_00000
            stem = entry.stem
            parts = stem.rsplit("_", 1)
            if len(parts) != 2 or not parts[1].isdigit():
                continue
            key, suffix = parts
            n = int(suffix)
            if n + 1 > counters.get(key, 0):
                counters[key] = n + 1
        return counters

    def __call__(self, datakey: str | None = None) -> PathInfo:
        """Return a fresh output path for *key* and advance its counter.

        Parameters
        ----------
        key : str | None
            Discriminator for the counter bucket — typically a plan name.
            ``None`` maps to ``"default"``.

        Returns
        -------
        Path
            Full path rooted at
            ``<base_dir>/<session>/<YYYY_MM_DD>/<key>[_<group>]_<counter>``.
        """
        resolved_key = datakey or "default"
        bucket = (
            f"{resolved_key}_{self.group}" if self.group is not None else resolved_key
        )
        current = self._counters.get(bucket, 0)

        if len(str(current)) > self._max_digits:
            raise ValueError(
                f"Counter for key {bucket!r} exceeded "
                f"maximum of {self._max_digits} digits"
            )

        padded = f"{current:0{self._max_digits}}"
        stem = (
            f"{resolved_key}_{self.group}_{padded}"
            if self.group
            else f"{resolved_key}_{padded}"
        )
        directory = self._base_dir / self._session / self._date
        directory.mkdir(parents=True, exist_ok=True)
        self._counters[bucket] = current + 1

        return PathInfo(
            directory_path=directory,
            filename=stem,
        )


__all__ = ["SessionPathProvider"]
