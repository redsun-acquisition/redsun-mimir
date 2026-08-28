"""Runnable example containers.

Each module exposes a ``build_*`` factory returning the container unbuilt -
so it can be built and inspected without entering the Qt event loop - and a
``run_*`` entry point used by the ``mimir`` CLI.
"""

from ._full_simulation import build_simulation_container, run_simulation_container
from ._full_uc2 import run_uc2_container

__all__ = [
    "build_simulation_container",
    "run_simulation_container",
    "run_uc2_container",
]
