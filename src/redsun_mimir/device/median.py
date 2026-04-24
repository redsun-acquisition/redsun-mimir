from __future__ import annotations

from typing import TYPE_CHECKING

from ophyd_async.core import StandardDetector

if TYPE_CHECKING:
    from ophyd_async.core import SignalR, SignalRW

    from redsun_mimir.protocols import Array2D, ROIType


class MedianDetector(StandardDetector):
    """A soft device that computes the median of a stack of images.

    Also allows the stack to be written to disk for post-processing.
    It is meant to be used as a child device in a concrete device.
    """

    def __init__(
        self,
        parent_name: str,
        buffer_sig: SignalR[Array2D],
        roi_sig: SignalRW[ROIType],
        dtype_sig: SignalR[str],
    ) -> None:
        super().__init__("median")
