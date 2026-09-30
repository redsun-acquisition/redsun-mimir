from __future__ import annotations

from collections.abc import Sequence  # noqa: TC003

import bluesky.plan_stubs as bps
from bluesky.preprocessors import set_run_key_decorator
from bluesky.utils import MsgGenerator  # noqa: TC002
from ophyd_async.core import TriggerInfo  # noqa: TC002

from redsun_mimir.protocols import ReadableFlyer  # noqa: TC001

__all__ = ["capture", "prepare_and_declare", "teardown_acquisition"]

#: Run key giving a capture a document cycle of its own, apart from the
#: enclosing live run.
_CAPTURE_RUN_KEY = "capture"


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
    """Complete, collect, and unstage detectors."""
    yield from bps.complete_all(*detectors, wait=True)
    yield from bps.collect(*detectors, name=stream_name)
    yield from bps.unstage_all(*detectors)


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
        yield from until
    yield from teardown_acquisition(detectors, stream_name)
    yield from bps.close_run()
    return uid
