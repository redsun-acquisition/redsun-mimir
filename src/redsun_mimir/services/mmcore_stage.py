"""One Micro-Manager stage, served over PVAccess.

Run as ``python -m redsun_mimir.services.mmcore_stage --adapter DemoCamera
--device DXYStage --axes x,y``. The PV prefix and the name come from the
environment a ``redsun`` session launches it with, so the session writes them
once.

The process owns its own ``CMMCorePlus``, so no Micro-Manager call is left on
the session's event loop.
"""

# ``fastcs`` ships no py.typed, so every class taken from it is ``Any`` here,
# and subclassing one is an error a stub would fix
# mypy: disable-error-code="misc"
from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from fastcs.attributes import AttributeIO, AttributeIORef, AttrR, AttrRW, AttrW
from fastcs.controllers import Controller
from fastcs.datatypes import Float
from pymmcore_plus import CMMCorePlus

from ._process import controller_id, identity_arguments, plain_logging, serve

if TYPE_CHECKING:
    from collections.abc import Iterable

#: Printed once a client can reach the stage's PVs.
READY: Final = "mmcore stage ready"

#: Seconds between two reads of a position.
POLL_PERIOD: Final = 0.2

#: What a position is served in.
UNITS: Final = "um"

#: The axes a lateral stage moves. The rest go through ``setPosition``.
LATERAL: Final = ("x", "y")

#: Where the axes sit under the service's prefix.
STAGE_GROUP: Final = "stage"


@dataclass
class AxisRef(AttributeIORef):
    """Names the axis an attribute reads and moves."""

    axis: str = ""


class StageIO(AttributeIO[float, AxisRef]):
    """Reads and moves one stage through Micro-Manager."""

    def __init__(self, core: CMMCorePlus, label: str) -> None:
        super().__init__()
        self._core = core
        self._label = label
        self._moving = asyncio.Lock()

    async def send(self, attr: AttrW[float, AxisRef], value: float) -> None:
        """Move the axis, and read back where it stopped.

        One move at a time: a lateral move reads the pair and writes the
        pair, so a move on the sibling axis in flight would carry a stale
        value for this one and put it back where it started.
        """
        async with self._moving:
            await asyncio.to_thread(self._move, attr.io_ref.axis, float(value))
        if isinstance(attr, AttrR):
            await self.update(attr)

    async def update(self, attr: AttrR[float, AxisRef]) -> None:
        """Read where the axis is."""
        await attr.update(await asyncio.to_thread(self._position, attr.io_ref.axis))

    def _position(self, axis: str) -> float:
        if axis not in LATERAL:
            return float(self._core.getPosition(self._label))
        x, y = self._core.getXYPosition(self._label)
        return float(x if axis == "x" else y)

    def _move(self, axis: str, value: float) -> None:
        """Send the axis on its way and wait for it to arrive.

        A stage travels, so the move blocks until the device reports itself
        done: a plan's move is finished when the axis really is there.
        """
        if axis not in LATERAL:
            self._core.setPosition(self._label, value)
        else:
            x, y = self._core.getXYPosition(self._label)
            self._core.setXYPosition(
                self._label,
                value if axis == "x" else x,
                value if axis == "y" else y,
            )
        self._core.waitForDevice(self._label)


class MMAxisController(Controller):
    """One axis of the stage."""

    def __init__(self, axis: str, io: StageIO) -> None:
        super().__init__(ios=[io])
        self.position = AttrRW(
            Float(units=UNITS),
            io_ref=AxisRef(axis=axis, update_period=POLL_PERIOD),
        )


class MMStageController(Controller):
    """A stage, its axes served as the named entries of ``stage``'s ``axis``."""

    def __init__(self, core: CMMCorePlus, label: str, axes: Iterable[str]) -> None:
        io = StageIO(core, label)
        super().__init__(ios=[io])
        self._core = core
        self._label = label

        group = Controller(ios=[io])
        for axis in axes:
            group.add_sub_controller(axis, MMAxisController(axis, io))
        stage = Controller(ios=[io])
        stage.add_sub_controller("axis", group)
        self.add_sub_controller(STAGE_GROUP, stage)

    async def disconnect(self) -> None:
        """Stop the stage and let go of the device."""
        await asyncio.to_thread(self._core.stop, self._label)


def build_controller(
    adapter: str, device: str, label: str, axes: Iterable[str]
) -> MMStageController:
    """Load the stage into a core of this process's own, and wrap it."""
    core = CMMCorePlus()
    core.loadDevice(label, adapter, device)
    core.initializeDevice(label)
    return MMStageController(core, label, axes)


def main(argv: list[str] | None = None) -> int:
    """Run the service, taking its identity from the session that launched it."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", required=True, help="Micro-Manager adapter")
    parser.add_argument("--device", required=True, help="device of that adapter")
    parser.add_argument(
        "--axes", default="x,y", help="axes the stage moves, comma separated"
    )
    identity_arguments(parser, "stage")
    options = parser.parse_args(argv)

    plain_logging()
    axes = [axis.strip() for axis in str(options.axes).split(",") if axis.strip()]
    controller: Any = build_controller(
        options.adapter, options.device, options.name, axes
    )
    asyncio.run(serve(controller, controller_id(options), READY))
    return 0


if __name__ == "__main__":
    sys.exit(main())
