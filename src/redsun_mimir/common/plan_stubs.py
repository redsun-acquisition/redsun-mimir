from __future__ import annotations

from typing import TYPE_CHECKING

import bluesky.plan_stubs as bps

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import Final

    from bluesky.protocols import Flyable
    from bluesky.utils import MsgGenerator

SIXTY_FPS: Final[float] = 1.0 / 60.0


def collect_while_waiting(
    objs: Sequence[Flyable],
    wait_group: str,
    stream_name: str,
    refresh_period: float = SIXTY_FPS,
) -> MsgGenerator[None]:
    """Collect data from the given Flyable objects while waiting.

    Parameters
    ----------
    objects : ``Sequence[EventCollectable]``
        The objects to collect data from.
    wait_group : ``str``
        The group identifier to wait on.
    stream_name : ``str``
        The name of the stream to collect data into.
    refresh_period : ``float``, optional
        The period (in seconds) to refresh the collection. Default is 60 Hz (1/60 s).

    Yields
    ------
    Msg
        Messages to wait and collect data from the objects.
    """
    done = False
    while not done:
        done = yield from bps.wait(
            group=wait_group, timeout=refresh_period, error_on_timeout=False
        )
        yield from bps.collect(
            *objs, name=stream_name, stream=True, return_payload=False
        )
