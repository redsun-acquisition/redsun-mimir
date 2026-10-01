from __future__ import annotations

from collections.abc import Sequence  # noqa: TC003

import bluesky.plan_stubs as bps
from bluesky.preprocessors import plan_mutator, set_run_key_decorator
from bluesky.utils import Msg, MsgGenerator  # noqa: TC002
from ophyd_async.core import TriggerInfo  # noqa: TC002

from redsun_mimir.protocols import ReadableFlyer  # noqa: TC001

__all__ = [
    "FLUSH_PERIOD",
    "capture",
    "collect_while_waiting",
    "prepare_and_declare",
    "teardown_acquisition",
]

#: Run key giving a capture a document cycle of its own, apart from the
#: enclosing live run.
_CAPTURE_RUN_KEY = "capture"

#: Seconds between two collects of a capture that is writing.
FLUSH_PERIOD = 0.5


def prepare_and_declare(
    detectors: Sequence[ReadableFlyer],
    trigger_info: TriggerInfo,
    stream_name: str,
    *,
    collect: bool = True,
    declare: bool = True,
) -> MsgGenerator[None]:
    """Prepare detectors and optionally declare their stream.

    Preparing starts live acquisition and hands each detector the sink it
    will write through; the write window opens at kickoff, so frames reach
    viewers but not storage until then. Staging is left to the caller, so
    several device groups can share one `stage_all` call.
    """
    for det in detectors:
        yield from bps.prepare(det, trigger_info, wait=True)
    if declare:
        yield from bps.declare_stream(*detectors, name=stream_name, collect=collect)


def teardown_acquisition(
    detectors: Sequence[ReadableFlyer],
    stream_name: str,
) -> MsgGenerator[None]:
    """Complete detectors, collecting what they write meanwhile, then unstage them."""
    yield from bps.collect_while_completing(
        detectors, detectors, flush_period=FLUSH_PERIOD, stream_name=stream_name
    )
    yield from bps.unstage_all(*detectors)


def collect_while_waiting(
    plan: MsgGenerator[None],
    detectors: Sequence[ReadableFlyer],
    stream_name: str,
    flush_period: float = FLUSH_PERIOD,
) -> MsgGenerator[None]:
    """Run *plan*, collecting *detectors* each time it has slept *flush_period* seconds.

    The time counted is what *plan* asks to sleep, so a plan waiting in a
    polling loop, such as one waiting for a user's action, collects the frames
    written while it waits.
    """
    slept = 0.0

    def collect_after_sleep(msg: Msg) -> tuple[None, MsgGenerator[None] | None]:
        nonlocal slept
        if msg.command != "sleep":
            return None, None
        slept += msg.args[0]
        if slept < flush_period:
            return None, None
        slept = 0.0
        return None, bps.collect(*detectors, name=stream_name)

    yield from plan_mutator(plan, collect_after_sleep)


@set_run_key_decorator(_CAPTURE_RUN_KEY)  # type: ignore[untyped-decorator]
def capture(
    detectors: Sequence[ReadableFlyer],
    stream_name: str,
    *,
    parent: str,
    median_scan: str | None = None,
    until: MsgGenerator[None] | None = None,
) -> MsgGenerator[str]:
    """Fly the prepared detectors to disk in a nested run and return its uid.

    The start document names *parent*, the run served, and *median_scan*,
    the scan whose stack goes into the store this capture names. With
    *until* the window stays open until that plan returns. The detectors are
    left unstaged for the next capture.
    """
    uid: str = yield from bps.open_run(
        md={"purpose": "capture", "parent": parent, "median_scan": median_scan}
    )
    yield from bps.declare_stream(*detectors, name=stream_name, collect=True)
    yield from bps.kickoff_all(*detectors, wait=True)
    if until is not None:
        yield from collect_while_waiting(until, detectors, stream_name)
    yield from teardown_acquisition(detectors, stream_name)
    yield from bps.close_run()
    return uid
