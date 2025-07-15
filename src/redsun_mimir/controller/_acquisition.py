from __future__ import annotations

from collections.abc import Mapping, Sequence  # noqa: TC003
from threading import Event
from typing import TYPE_CHECKING

import bluesky.plan_stubs as bps
import in_n_out as ino
from bluesky.utils import MsgGenerator  # noqa: TC002
from sunflare.engine import RunEngine
from sunflare.log import Loggable
from sunflare.virtual import Publisher, Signal, VirtualBus

from redsun_mimir.common import PlanManifest, generate_plan_manifest
from redsun_mimir.protocols import DetectorProtocol  # noqa: TC001
from redsun_mimir.utils import togglable

if TYPE_CHECKING:
    from typing import Any, Callable, Mapping

    from sunflare.model import ModelProtocol

    from ._config import AcquisitionControllerInfo

store = ino.Store.create("PlanManifest")


class AcquisitionController(Publisher, Loggable):
    sigPlansManifest = Signal(object)
    sigPlanDone = Signal()

    def __init__(
        self,
        ctrl_info: AcquisitionControllerInfo,
        models: Mapping[str, ModelProtocol],
        virtual_bus: VirtualBus,
    ) -> None:
        super().__init__(virtual_bus)
        self.ctrl_info = ctrl_info
        self.virtual_bus = virtual_bus
        self.models = models
        self.live_event = Event()
        self.engine = RunEngine(socket_prefix="ACQ", socket=self.pub_socket)

        # type annotating "plans" seems the only way to
        # make mypy happy here; a list comprehension
        # would be enough but it is what it is
        plans: list[Callable[..., MsgGenerator[Any]]] = [self.live_count, self.snap]
        self.manifests: set[PlanManifest] = set(
            [generate_plan_manifest(plan, models) for plan in plans]
        )

        store.register_provider(self.plans_manifests)

    def registration_phase(self) -> None:
        self.virtual_bus.register_signals(self)

    def plans_manifests(self) -> set[PlanManifest]:
        return self.manifests

    def connection_phase(self) -> None: ...

    @togglable
    def live_count(self, detectors: Sequence[DetectorProtocol]) -> MsgGenerator[None]:
        """Start a live acquisition with the selected detectors.

        Parameters
        ----------
        detectors : ``Sequence[DetectorProtocol]``
            The detectors to use in the live acquisition.
        """
        self.live_event.set()
        yield from bps.stage_all(detectors)
        while self.live_event.is_set():
            yield from bps.trigger_and_read(detectors, name="live-stream")
        yield from bps.unstage_all(detectors)

    def snap(
        self, detectors: Sequence[DetectorProtocol], num_frames: int = 1
    ) -> MsgGenerator[None]:
        """Take ``num_frames`` snapshot from each detector.

        Parameters
        ----------
        detectors : ``Sequence[DetectorProtocol]``
            The detectors to take a snapshot from.
        num_frames : ``int``, optional
            The number of snapshots to take for each detector.
            Must be a non-zero, positive integer.
            Default is 1.
        """
        if num_frames <= 0:
            raise ValueError("Number of frames must be a positive integer.")

        yield from bps.stage_all(detectors)
        for _ in range(num_frames):
            yield from bps.trigger_and_read(detectors, name="snap-stream")
        yield from bps.unstage_all(detectors)
