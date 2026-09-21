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


def session_logging() -> None:
    """Log as JSON lines the session rebuilds into records of its own.

    A serialized ``loguru`` record keeps its level, time, logger name and
    traceback; a plain line would arrive as DEBUG text.
    """
    logger.remove()
    logger.add(sys.stdout, serialize=True, level="INFO")


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

    The prefix without its trailing colon, which a PVA id takes none of.
    """
    return str(options.prefix).rstrip(":") or str(options.name)


async def announce_when_reachable(prefix: str, ready: str) -> None:
    """Print *ready* once the controller's PVI record answers.

    The check looks on the loopback interface, since the session's search
    list is set on its own process, not this one.
    """
    from p4p.client.asyncio import Context

    with Context("pva", conf={"EPICS_PVA_ADDR_LIST": LOOPBACK}) as client:
        while True:
            try:
                await asyncio.wait_for(client.get(f"{prefix}:PVI"), timeout=1.0)
            except TimeoutError:
                continue
            except Exception as error:  # noqa: BLE001
                # the session waits for the line this prints, so a failure
                # here would otherwise show up only as its own timeout
                logger.warning(f"Readiness check failed, retrying: {error}")
                continue
            break
    print(ready, flush=True)


async def serve(controller: Controller, prefix: str, ready: str) -> None:
    """Serve *controller* over PVA until this process's standard input closes.

    ``FastCS.run`` installs signal handlers POSIX only and watches no input,
    so the serving task is cancelled here instead.
    """
    controller.set_path([prefix])
    control_system = FastCS(controller, [EpicsPVATransport()])
    serving = asyncio.ensure_future(control_system.serve(interactive=False))
    announcing = asyncio.ensure_future(announce_when_reachable(prefix, ready))

    await asyncio.to_thread(sys.stdin.read)

    announcing.cancel()
    serving.cancel()
    await asyncio.gather(serving, announcing, return_exceptions=True)
