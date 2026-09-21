"""A camera's region of interest, as it travels between the service and a view."""

from __future__ import annotations

from typing import NamedTuple


class Roi(NamedTuple):
    """A rectangle of sensor pixels, ``x, y, width, height`` from the top left.

    Written as text, ``"x,y,width,height"``, on a camera's ``roi`` signal:
    that is what a client can put over PVAccess, an array being refused.
    """

    x: int
    y: int
    width: int
    height: int

    @classmethod
    def parse(cls, text: str) -> Roi:
        """Read a ROI from ``"x,y,width,height"``, spaces around the numbers allowed.

        Raises
        ------
        ValueError
            If the text is not four integers.
        """
        parts = text.split(",")
        if len(parts) != 4:
            raise ValueError(f"a ROI is four integers, x,y,width,height, not {text!r}")
        return cls(*(int(part) for part in parts))

    def __str__(self) -> str:
        """Return the ROI as ``"x,y,width,height"``."""
        return f"{self.x},{self.y},{self.width},{self.height}"


__all__ = ["Roi"]
