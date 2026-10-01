"""What every mimir service does around its `fastcs` controller.

A service takes its name, its PV prefix, its ready text and its stop request
from the session that launched it, through `redsun.services`.
"""

from __future__ import annotations

import asyncio
import faulthandler
from typing import TYPE_CHECKING, Any, Final

from fastcs.control_system import FastCS
from fastcs.transports.epics.pva.transport import EpicsPVATransport
from redsun.services import identity, ready_when_reachable, wait_for_stop

if TYPE_CHECKING:
    import argparse
    from collections.abc import Coroutine

    from fastcs.controllers import Controller

#: Seconds a service may take to become ready, or to stop once asked, before
#: it writes every thread's stack to its output. Below the 15 s a session
#: waits for readiness, so the stacks reach the session's log.
STALL_DUMP: Final = 10.0


def identity_arguments(parser: argparse.ArgumentParser, default_name: str) -> None:
    """Add the name and prefix a session gives a service it launches."""
    me = identity()
    parser.add_argument(
        "--prefix",
        default=me.prefix if me else "",
        help="PV prefix, the session's unless given",
    )
    parser.add_argument(
        "--name",
        default=me.name if me else default_name,
        help="name of this service, the session's unless given",
    )


def controller_id(options: argparse.Namespace) -> str:
    """Return the id the controller is served under.

    The prefix without its trailing colon, which a PVA id takes none of.
    """
    return str(options.prefix).rstrip(":") or str(options.name)


async def serve(controller: Controller, prefix: str) -> None:
    """Serve *controller* over PVA until the session, or Ctrl+C, stops this service.

    `FastCS.run` installs signal handlers on POSIX only and watches no input,
    so the serving task is cancelled here instead.
    """
    faulthandler.dump_traceback_later(STALL_DUMP)
    controller.set_path([prefix])
    control_system = FastCS(controller, [EpicsPVATransport()])
    serving = asyncio.ensure_future(control_system.serve(interactive=False))
    announcing = asyncio.ensure_future(ready_when_reachable(f"{prefix}:PVI"))
    announcing.add_done_callback(lambda _: faulthandler.cancel_dump_traceback_later())

    try:
        await wait_for_stop()
    finally:
        faulthandler.dump_traceback_later(STALL_DUMP)
        announcing.cancel()
        serving.cancel()
        await asyncio.gather(serving, announcing, return_exceptions=True)
        faulthandler.cancel_dump_traceback_later()


def run(serving: Coroutine[Any, Any, None]) -> int:
    """Run *serving* until the session or Ctrl+C stops it; return the exit code.

    Ctrl+C, the way a service run on its own is stopped, counts as a clean
    stop: `asyncio.run` has cancelled and awaited *serving* before it raises.
    """
    try:
        asyncio.run(serving)
    except KeyboardInterrupt:
        pass
    return 0
