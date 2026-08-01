from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MMAdapterInfo:
    """Information about a Micro-Manager adapter and its devices."""

    adapter: str
    """Adapter name as recognized by the Micro-Manager Core."""

    device: str
    """Device name as recognized by the Micro-Manager Core."""
