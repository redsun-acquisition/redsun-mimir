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
TRACEBACK_DELAY: Final = 10.0


def identity_arguments(parser: argparse.ArgumentParser, default_name: str) -> None:
    """Add the name and prefix a session gives a service it launches."""
    service = identity()
    parser.add_argument(
        "--prefix",
        default=service.prefix if service else "",
        help="PV prefix, the session's unless given",
    )
    parser.add_argument(
        "--name",
        default=service.name if service else default_name,
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
    faulthandler.dump_traceback_later(TRACEBACK_DELAY)
    controller.set_path([prefix])
    control_system = FastCS(controller, [EpicsPVATransport()])
    serve_task = asyncio.ensure_future(control_system.serve(interactive=False))
    ready_task = asyncio.ensure_future(ready_when_reachable(f"{prefix}:PVI"))
    ready_task.add_done_callback(lambda _: faulthandler.cancel_dump_traceback_later())

    try:
        await wait_for_stop()
    finally:
        faulthandler.dump_traceback_later(TRACEBACK_DELAY)
        ready_task.cancel()
        serve_task.cancel()
        await asyncio.gather(serve_task, ready_task, return_exceptions=True)
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
