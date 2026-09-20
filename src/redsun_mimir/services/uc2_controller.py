"""One YouSeeToo (UC2) board, served over PVAccess.

Run as ``python -m redsun_mimir.services.uc2_controller --port COM4``. The PV
prefix and the name come from the environment a ``redsun`` session launches it
with, so the session writes them once.

The process owns the serial port: every axis and every laser of the board is
commanded from here, under one lock, which is what the port itself requires.
"""

# ``fastcs`` ships no py.typed, so every class taken from it is ``Any`` here,
# and subclassing one is an error a stub would fix
# mypy: disable-error-code="misc"
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from dataclasses import dataclass
from threading import Lock
from typing import TYPE_CHECKING, Any, Final

from fastcs.attributes import AttributeIO, AttributeIORef, AttrR, AttrRW, AttrW
from fastcs.controllers import Controller
from fastcs.datatypes import Float, Int
from fastcs.logging import logger
from serial import Serial, serial_for_url

from ._process import controller_id, identity_arguments, plain_logging, serve
from ._uc2_serial import AXIS_ID, CONVERSION, move_axis, set_laser

if TYPE_CHECKING:
    from collections.abc import Iterable

#: Printed once a client can reach the board's PVs.
READY: Final = "uc2 controller ready"

#: The axes a board carries, in the order they are served.
AXES: Final = ("x", "y", "z")

#: What the stage holding those axes is served as.
STAGE_GROUP: Final = "stage"

#: The units a position is commanded in.
UNITS: Final = "um"

#: What a laser takes, in the controller's own counts.
LASER_RANGE: Final = (0, 1023)

#: Seconds the board is held in reset, and then waited on, at startup.
RESET_HOLD: Final = 0.5
RESET_SETTLE: Final = 2.0

#: What the board prints once it has restarted.
RESET_DONE: Final = b"{'setup': 'done'}"


@dataclass
class SerialRef(AttributeIORef):
    """Names what a command written to this attribute drives.

    Exactly one of the two is set: an axis by its name, a laser by its id.
    """

    axis: str = ""
    laser: int = 0


class SerialIO(AttributeIO[Any, SerialRef]):
    """Commands the board, and echoes back what was commanded.

    The board reports nothing of its own, so the readback of an attribute is
    the value whose command it acknowledged.
    """

    def __init__(self, serial: Serial, lock: Lock) -> None:
        super().__init__()
        self._serial = serial
        self._lock = lock

    async def send(self, attr: AttrW[Any, SerialRef], value: Any) -> None:
        """Send *value* to the board, and adopt it once it is acknowledged."""
        ref = attr.io_ref
        if ref.axis:
            await asyncio.to_thread(
                move_axis,
                self._serial,
                self._lock,
                AXIS_ID[ref.axis],
                CONVERSION[UNITS],
                float(value),
            )
        else:
            await asyncio.to_thread(
                set_laser, self._serial, self._lock, ref.laser, ref.laser, int(value)
            )
        if isinstance(attr, AttrR):
            await attr.update(value)

    async def update(self, attr: AttrR[Any, SerialRef]) -> None:
        """Do nothing: the board answers no query."""


class UC2AxisController(Controller):
    """One axis of the board's stage."""

    def __init__(self, axis: str, io: SerialIO) -> None:
        super().__init__(ios=[io])
        self.position = AttrRW(Float(units=UNITS), io_ref=SerialRef(axis=axis))


class UC2LaserController(Controller):
    """One laser of the board."""

    def __init__(self, laser: int, io: SerialIO) -> None:
        super().__init__(ios=[io])
        self.intensity = AttrRW(
            Int(min=LASER_RANGE[0], max=LASER_RANGE[1]), io_ref=SerialRef(laser=laser)
        )


class UC2Controller(Controller):
    """The board: a stage holding its axes, and a controller per laser.

    The nesting is what a client device reads: it connects to ``stage`` or to
    ``laser<n>``, and the axes are the named entries of ``stage``'s ``axis``,
    which is how ophyd-async fills a ``DeviceMap``.
    """

    def __init__(
        self, serial: Serial, axes: Iterable[str] = AXES, lasers: Iterable[int] = (1,)
    ) -> None:
        io = SerialIO(serial, Lock())
        super().__init__(ios=[io])
        self._serial = serial

        axes_group = Controller(ios=[io])
        for axis in axes:
            axes_group.add_sub_controller(axis, UC2AxisController(axis, io))
        stage = Controller(ios=[io])
        stage.add_sub_controller("axis", axes_group)
        self.add_sub_controller(STAGE_GROUP, stage)

        for laser in lasers:
            self.add_sub_controller(f"laser{laser}", UC2LaserController(laser, io))

    async def disconnect(self) -> None:
        """Close the serial port."""
        if self._serial.is_open:
            self._serial.close()


def open_board(port: str, baudrate: int, timeout: float) -> Serial:
    """Open the port and restart the board on it.

    The board runs its own setup on reset and prints when it is done, so a
    command sent before that is lost. *port* is anything ``pyserial`` opens by
    url, a device name such as ``COM4`` included.
    """
    serial = serial_for_url(port, baudrate=baudrate, timeout=timeout)
    serial.dtr = False
    serial.rts = True
    time.sleep(RESET_HOLD)
    serial.rts = False
    time.sleep(RESET_SETTLE)
    answer = serial.read_until(expected=RESET_DONE)
    if answer:
        logger.info(f"Board restarted: {answer.decode(errors='ignore').strip()}")
    return serial


def main(argv: list[str] | None = None) -> int:
    """Run the service, taking its identity from the session that launched it."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="serial port of the board")
    parser.add_argument("--baudrate", type=int, default=115200, help="baud rate")
    parser.add_argument("--timeout", type=float, default=3.0, help="read timeout, s")
    identity_arguments(parser, "uc2")
    options = parser.parse_args(argv)

    plain_logging()
    controller = UC2Controller(
        open_board(options.port, options.baudrate, options.timeout)
    )
    asyncio.run(serve(controller, controller_id(options), READY))
    return 0


if __name__ == "__main__":
    sys.exit(main())
