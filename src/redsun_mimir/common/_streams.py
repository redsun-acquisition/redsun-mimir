"""Event stream names shared by plans and document consumers.

Live visualization travels as Event documents from ``bps.monitor`` on a
buffer signal, not as signal subscriptions, so what a viewer shows is part of
the run's document sequence and can be traced, replayed and written. Plans
emit these names; `DocumentRouter` presenters route on them.
"""

from __future__ import annotations

#: Live visualization frames, emitted by ``bps.monitor`` on a buffer signal.
LIVE_VIEW_STREAM = "live_view"

#: Background stack collected by a square scan, emitted as its own nested run.
MEDIAN_SCAN_STREAM = "median_scan"

__all__ = ["LIVE_VIEW_STREAM", "MEDIAN_SCAN_STREAM"]
