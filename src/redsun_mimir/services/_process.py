"""What every mimir service does around its ``fastcs`` controller.

A service is launched by a session, told its name and its PV prefix through
the environment, and stopped by closing its standard input.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import TYPE_CHECKING, Final

from fastcs.control_system import FastCS
from fastcs.logging import logger
from fastcs.transports.epics.pva.transport import EpicsPVATransport

if TYPE_CHECKING:
    import argparse

    from fastcs.controllers import Controller

#: Where the readiness check looks for the controller it just served.
LOOPBACK: Final = "127.0.0.1"

#: What a line of a service's own logging looks like.
LOG_FORMAT: Final = "{level} {message}"


def plain_logging() -> None:
    """Log without colour.

    The session reads a service's output line by line into its own log file,
    where the escape sequences ``fastcs`` writes by default would land as
    text.
    """
    logger.remove()
    logger.add(sys.stdout, colorize=False, level="INFO", format=LOG_FORMAT)


def identity_arguments(parser: argparse.ArgumentParser, default_name: str) -> None:
    """Add the name and prefix a session gives a service through its environment."""
    parser.add_argument(
        "--prefix",
        default=os.environ.get("REDSUN_SERVICE_PREFIX", ""),
        help="PV prefix, REDSUN_SERVICE_PREFIX unless given",
    )
    parser.add_argument(
        "--name",
        default=os.environ.get("REDSUN_SERVICE_NAME", default_name),
        help="name of this service, REDSUN_SERVICE_NAME unless given",
    )


def controller_id(options: argparse.Namespace) -> str:
    """Return the id the controller is served under.

    A PVA id takes no colon, while the prefix a client device is given ends in
    one, so the id is the prefix without it.
    """
    return str(options.prefix).rstrip(":") or str(options.name)


async def announce_when_reachable(prefix: str, ready: str) -> None:
    """Print *ready* once the controller's PVI record answers.

    The session tells its own process where to search, not this one, so the
    check looks on the interface the controller is served on.
    """
    from p4p.client.asyncio import Context

    with Context("pva", conf={"EPICS_PVA_ADDR_LIST": LOOPBACK}) as client:
        while True:
            try:
                await asyncio.wait_for(client.get(f"{prefix}:PVI"), timeout=1.0)
            except TimeoutError:
                continue
            break
    print(ready, flush=True)


async def serve(controller: Controller, prefix: str, ready: str) -> None:
    """Serve *controller* over PVA until this process's standard input closes.

    ``FastCS.run`` installs signal handlers POSIX only and watches no input,
    so the serving task is cancelled here instead.
    """
    control_system = FastCS(controller, [EpicsPVATransport()])
    controller.set_path([prefix])
    serving = asyncio.ensure_future(control_system.serve(interactive=False))
    announcing = asyncio.ensure_future(announce_when_reachable(prefix, ready))

    await asyncio.to_thread(sys.stdin.read)

    announcing.cancel()
    serving.cancel()
    await asyncio.gather(serving, announcing, return_exceptions=True)
