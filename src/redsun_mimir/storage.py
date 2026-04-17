"""Storage utilities for redsun-mimir.

Provides path management helpers that were previously part of the
``redsun.storage`` public API.
"""

from __future__ import annotations

import datetime
from pathlib import Path


class SessionPathProvider:
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
        self._session = session
        self._max_digits = max_digits
        self._date = datetime.datetime.now().strftime("%Y_%m_%d")
        self._counters: dict[str, int] = self._scan_existing()

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
            if not entry.is_dir():
                continue
            parts = entry.name.rsplit("_", 1)
            if len(parts) != 2 or not parts[1].isdigit():
                continue
            key, suffix = parts
            n = int(suffix)
            if n + 1 > counters.get(key, 0):
                counters[key] = n + 1
        return counters

    def __call__(self, key: str | None = None, group: str | None = None) -> Path:
        """Return a fresh output path for *key* and advance its counter.

        Parameters
        ----------
        key : str | None
            Discriminator for the counter bucket — typically a plan name.
            ``None`` maps to ``"default"``.
        group : str | None
            Writer group name.  When provided, the filename becomes
            ``<key>_<group>_<counter>`` and the counter is tracked
            independently per ``(key, group)`` pair.

        Returns
        -------
        Path
            Full path rooted at
            ``<base_dir>/<session>/<YYYY_MM_DD>/<key>[_<group>]_<counter>``.
        """
        resolved_key = key or "default"
        bucket = f"{resolved_key}_{group}" if group else resolved_key
        current = self._counters.get(bucket, 0)

        if len(str(current)) > self._max_digits:
            raise ValueError(
                f"Counter for key {bucket!r} exceeded "
                f"maximum of {self._max_digits} digits"
            )

        padded = f"{current:0{self._max_digits}}"
        stem = (
            f"{resolved_key}_{group}_{padded}" if group else f"{resolved_key}_{padded}"
        )
        directory = self._base_dir / self._session / self._date
        directory.mkdir(parents=True, exist_ok=True)
        self._counters[bucket] = current + 1
        return directory / stem


__all__ = ["SessionPathProvider"]
