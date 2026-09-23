from __future__ import annotations

import threading
from typing import TYPE_CHECKING, TypeVar
from uuid import uuid4

import bluesky.preprocessors as bpp
from bluesky.utils import Msg
from psygnal import Signal

if TYPE_CHECKING:
    from bluesky import RunEngine
    from bluesky.protocols import HasName
    from bluesky.utils import MsgGenerator

T = TypeVar("T")


class DeviceLocks:
    """The devices a running plan uses, so views can disable their controls.

    `register` it on the engine running the plans; a plan then locks devices
    with `lock_wrapper`. A view connects `sig_locks_changed` and disables the
    input widgets of every device named, leaving its readouts as they are.

    Each lock is named by a token, so a device locked twice stays locked until
    both are released, and a ``lock`` message the engine replays after a
    rewind replaces its own entry rather than adding another.
    """

    sig_locks_changed = Signal(frozenset)
    """The names of the locked devices, whenever that set changes."""

    def __init__(self) -> None:
        self._held: dict[str, frozenset[str]] = {}
        # plans lock devices on the engine's thread, views read on the main one
        self._guard = threading.Lock()

    @property
    def locked(self) -> frozenset[str]:
        """The names of the devices locked now."""
        with self._guard:
            return frozenset().union(*self._held.values())

    def register(self, engine: RunEngine) -> None:
        """Handle the ``lock`` and ``unlock`` messages of *engine*."""
        engine.register_command("lock", self._lock)
        engine.register_command("unlock", self._unlock)

    async def _lock(self, msg: Msg) -> None:
        self._update(msg.kwargs["token"], {device.name for device in msg.args})

    async def _unlock(self, msg: Msg) -> None:
        self._update(msg.kwargs["token"], None)

    def _update(self, token: str, names: set[str] | None) -> None:
        """Hold *names* under *token*, or release the token when *names* is None."""
        with self._guard:
            before = frozenset().union(*self._held.values())
            if names is None:
                self._held.pop(token, None)
            else:
                self._held[token] = frozenset(names)
            after = frozenset().union(*self._held.values())
        if after != before:
            self.sig_locks_changed.emit(after)


def lock_wrapper(plan: MsgGenerator[T], *devices: HasName) -> MsgGenerator[T]:
    """Run *plan* with *devices* locked, unlocking them however it ends.

    Needs an engine a `DeviceLocks` is registered on.
    """
    token = uuid4().hex

    def locked() -> MsgGenerator[T]:
        yield Msg("lock", None, *devices, token=token)
        return (yield from plan)

    def unlock() -> MsgGenerator[None]:
        yield Msg("unlock", None, token=token)

    result: T = yield from bpp.finalize_wrapper(locked(), unlock())
    return result
