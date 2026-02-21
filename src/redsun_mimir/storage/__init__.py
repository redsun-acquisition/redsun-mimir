"""Deprecated storage module — use `sunflare.storage` instead.

This module re-exports the storage classes that were previously defined
here.  All names have been upstreamed to ``sunflare.storage`` as of
sunflare 0.11.0 and will be removed from ``redsun_mimir.storage`` in a
future release.
"""

import warnings as _warnings

from sunflare.storage import Writer, ZarrWriter

__all__ = ["Writer", "ZarrWriter"]


def __getattr__(name: str) -> object:
    if name in __all__:
        _warnings.warn(
            f"Importing '{name}' from 'redsun_mimir.storage' is deprecated "
            f"and will be removed in a future release. "
            f"Use 'sunflare.storage.{name}' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return globals()[name]
    raise AttributeError(f"module 'redsun_mimir.storage' has no attribute {name!r}")
