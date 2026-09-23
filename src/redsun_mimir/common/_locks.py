from __future__ import annotations

import threading
from collections import Counter
from contextlib import contextmanager
from typing import TYPE_CHECKING

from psygnal import Signal

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from ophyd_async.core import Device


class DeviceLocks:
    """The devices a running plan uses, so views can disable their controls.

    A plan holds the devices it must not have disturbed, for as long as it
    needs them. A view connects `sig_locks_changed` and disables the input
    widgets of every device named, leaving its readouts as they are:

    ```python
    def scan(self, stage: Stage, camera: Camera) -> MsgGenerator[None]:
        with self.locks.hold(self.laser):
            yield from bps.mv(self.laser.power, 5)
    ```

    Holds on one device add up, so it stays locked until the last one ends.
    A hold ends with its ``with`` block, so a plan that is stopped or aborted
    releases what it held when its generator is closed.
    """

    sig_locks_changed = Signal(frozenset)
    """The names of the locked devices, whenever that set changes."""

    def __init__(self) -> None:
        self._counts: Counter[str] = Counter()
        # plans hold devices on the engine's thread, views read on the main one
        self._guard = threading.Lock()

    @property
    def locked(self) -> frozenset[str]:
        """The names of the devices held now."""
        with self._guard:
            return frozenset(self._counts)

    @contextmanager
    def hold(self, *devices: Device) -> Iterator[None]:
        """Keep *devices* locked until the ``with`` block ends."""
        names = [device.name for device in devices]
        self._update(names, 1)
        try:
            yield
        finally:
            self._update(names, -1)

    def _update(self, names: Iterable[str], step: int) -> None:
        with self._guard:
            before = frozenset(self._counts)
            self._counts.update({name: step for name in names})
            for name in [name for name, count in self._counts.items() if count <= 0]:
                del self._counts[name]
            after = frozenset(self._counts)
        if after != before:
            self.sig_locks_changed.emit(after)
