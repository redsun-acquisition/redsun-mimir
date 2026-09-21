"""Shared fixtures for redsun-mimir tests."""

from __future__ import annotations

import logging
import os
import sys
from functools import cached_property
from typing import TYPE_CHECKING

import numpy as np
import pytest
from ophyd_async.core import (
    DeviceMap,
    MovableLogic,
    StandardMovable,
    StandardReadable,
    StandardReadableFormat,
    soft_signal_r_and_setter,
    soft_signal_rw,
)
from pymmcore_plus import CMMCorePlus as Core
from pymmcore_plus import find_micromanager
from qtpy.QtWidgets import QApplication
from redsun.aio import get_shared_loop
from redsun.path_provider import SessionPathProvider
from redsun.services import Service
from redsun.services._transports import PV_ACCESS, TRANSPORTS, PVAccess
from redsun.virtual import VirtualContainer

from redsun_mimir.device._mocks import MockLightDevice
from redsun_mimir.device.mmcore import MMCamera, MMStage
from redsun_mimir.services.mmcore_camera import READY
from redsun_mimir.services.mmcore_stage import READY as STAGE_READY
from redsun_mimir.services.uc2_controller import READY as UC2_READY

if TYPE_CHECKING:
    from typing import Protocol

    class ServiceFactory(Protocol):
        """Launches one service for the duration of a test."""

        def __call__(
            self, name: str, prefix: str, module: str, ready: str, *args: str
        ) -> Service: ...

    import asyncio
    from collections.abc import AsyncGenerator, Generator, Iterator
    from pathlib import Path

    from qtpy.QtCore import QCoreApplication

#: PV prefix the camera service serves under while the tests run.
CAMERA_PREFIX = "MIMIR-TESTCAM:"

#: PV prefix the stage service serves under while the tests run.
STAGE_PREFIX = "MIMIR-TESTXY:"

#: PV prefix the YouSeeToo service serves under while the tests run.
UC2_PREFIX = "MIMIR-TEST-UC2:"

#: Seconds a device may take to connect. A service of its own has to start
#: first, and several of them do while the whole suite runs.
CONNECT_TIMEOUT = 30.0

# p4p logs a subscription's keyword arguments as ``_log.debug("Subscription(%s)",
# kws)``; ``logging`` reads that single dict as a mapping and raises
# ``TypeError: not all arguments converted during string formatting`` wherever a
# handler formats the record, which fails the monitor the record came from
logging.getLogger("p4p.client.raw").setLevel(logging.INFO)


#: Micro-Manager device adapters are downloaded, not pip-installed, and their
#: device interface version must match the installed ``pymmcore``. Tests that
#: load a real device are skipped when none are discoverable.
needs_mm_adapters = pytest.mark.skipif(
    find_micromanager() is None,
    reason="no Micro-Manager device adapters; run 'mmcore install --test-adapters'",
)

#: A napari viewer needs a real OpenGL context - ``QT_QPA_PLATFORM=offscreen``
#: cannot provide one and construction dies inside PyOpenGL. Opt in on a machine
#: with a display.
HAS_OPENGL = bool(os.environ.get("MIMIR_TEST_OPENGL"))
NO_OPENGL_REASON = "napari needs a real OpenGL context; set MIMIR_TEST_OPENGL=1 to run"

needs_opengl = pytest.mark.skipif(not HAS_OPENGL, reason=NO_OPENGL_REASON)


class FakeAxis(StandardReadable, StandardMovable[float]):
    """Soft-signal stand-in for one movable axis.

    Built like the production axes: a readback separate from the setpoint,
    joined by a `MovableLogic`. The setter writes the readback, so a move
    lands exactly where it was sent.
    """

    def __init__(self, name: str = "") -> None:
        with self.add_children_as_readables():
            self.readback, self._readback_set = soft_signal_r_and_setter(
                float, 0.0, units="um"
            )

        async def setter(value: float | None) -> float | None:
            if value is not None:
                self._readback_set(value)
            return value

        self.setpoint = soft_signal_rw(float, 0.0, units="um", setter=setter)
        super().__init__(name)

    @cached_property
    def movable_logic(self) -> MovableLogic[float]:
        """Setpoint and readback of this axis."""
        return MovableLogic(setpoint=self.setpoint, readback=self.readback)


class FakeXYStage(StandardReadable):
    """Minimal ``MotorProtocol``-conformant test double for an XY stage.

    Presenter/view/acquisition-layer tests only need *some* device that
    structurally satisfies
    [`MotorProtocol`][redsun_mimir.protocols.MotorProtocol] whose axes show
    up in ``read()``/``describe()``. Using this instead of ``MMDemoXYStage``
    keeps those tests off the process-wide ``CMMCorePlus`` singleton, which
    only tolerates one device per name.

    It is built exactly like the production stages: axes go straight into the
    ``DeviceMap`` and are never bound as top-level attributes first (a
    ``Device`` cannot be re-parented), and they are registered with
    [`add_readables`][ophyd_async.core.StandardReadable.add_readables] so
    readings are keyed ``<device>-axis-<name>``.
    """

    axis: DeviceMap[StandardMovable[float]]

    def __init__(self, name: str, /, axes: tuple[str, ...] = ("x", "y")) -> None:
        self.axis = DeviceMap({axis: FakeAxis() for axis in axes})
        self.add_readables(list(self.axis.values()))
        super().__init__(name)


@pytest.fixture(scope="session", autouse=True)
def qapp() -> Generator[QCoreApplication, None, None]:
    """Session-scoped QApplication instance."""
    if (
        sys.platform == "linux"
        and os.environ.get("QT_QPA_PLATFORM") != "offscreen"
        and not os.environ.get("DISPLAY")
    ):
        pytest.skip("requires a display (Qt) on Linux")
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture(scope="session", autouse=True)
def shared_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Ensure the shared event loop is running in its background daemon thread."""
    loop = get_shared_loop()
    yield loop


@pytest.fixture(autouse=True)
def _reset_mmcore() -> Generator[None, None, None]:
    """Unload every Micro-Manager device after each test.

    MM devices are loaded by name into a process-wide ``CMMCorePlus``
    singleton (and only one camera device may be active at a time); leaving
    them loaded would collide with the next test reusing the same name or
    claiming the single camera slot.
    """
    yield
    Core.instance().reset()


@pytest.fixture
def virtual_container() -> VirtualContainer:
    """Fresh VirtualContainer for each test."""
    return VirtualContainer()


class FakeDetector(StandardReadable):
    """A ``DetectorProtocol`` double on soft signals, its sensor 6 wide and 4 high.

    For the presenter and view layers, which read a detector's settings and
    place its frames but never take one. Non-square, so a width taken for a
    height shows.
    """

    def __init__(self, name: str, /) -> None:
        with self.add_children_as_readables(StandardReadableFormat.CONFIG_SIGNAL):
            self.exposure = soft_signal_rw(float, initial_value=10.0)
            self.roi = soft_signal_rw(np.ndarray, initial_value=np.array([0, 0, 6, 4]))
            self.pixel_dtype, _ = soft_signal_r_and_setter(str, initial_value="uint8")
            self.sensor_size, _ = soft_signal_r_and_setter(
                np.ndarray, initial_value=np.array([6, 4])
            )
        self.buffer, _ = soft_signal_r_and_setter(
            np.ndarray, initial_value=np.zeros((4, 6), dtype=np.uint8)
        )
        super().__init__(name)


@pytest.fixture
async def fake_detector() -> FakeDetector:
    """Return a connected ``FakeDetector``."""
    device = FakeDetector("cam")
    await device.connect(mock=True)
    return device


@pytest.fixture
async def motor_stage() -> FakeXYStage:
    """Return a connected two-axis ``FakeXYStage`` double (see class docstring)."""
    device = FakeXYStage("xystage")
    await device.connect(mock=True)
    return device


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> Iterator[ServiceFactory]:
    """Return a factory launching one service, stopped when the test ends.

    Each test gets its own transport object: the one a session holds adds the
    loopback to this process's address list once, and the list is cleared here
    between tests.
    """
    monkeypatch.setenv("EPICS_PVA_ADDR_LIST", "")
    monkeypatch.setitem(TRANSPORTS, PV_ACCESS, PVAccess())
    started: list[Service] = []

    def launch(name: str, prefix: str, module: str, ready: str, *args: str) -> Service:
        running = Service(
            name,
            prefix=prefix,
            module=module,
            args=list(args),
            ready=ready,
            transport=PV_ACCESS,
            stop_timeout=10,
        )
        running.start()
        started.append(running)
        return running

    yield launch
    for running in started:
        running.stop()


@pytest.fixture
def camera_service(service: ServiceFactory) -> Service:
    """Launch the camera service on the demo adapter."""
    return service(
        "camera1",
        CAMERA_PREFIX,
        "redsun_mimir.services.mmcore_camera",
        READY,
        "--adapter",
        "DemoCamera",
        "--device",
        "DCam",
    )


@pytest.fixture
def stage_service(service: ServiceFactory) -> Service:
    """Launch the stage service on the demo XY stage."""
    return service(
        "XY",
        STAGE_PREFIX,
        "redsun_mimir.services.mmcore_stage",
        STAGE_READY,
        "--adapter",
        "DemoCamera",
        "--device",
        "DXYStage",
        "--axes",
        "x,y",
    )


@pytest.fixture
def uc2_service(service: ServiceFactory) -> Service:
    """Launch the UC2 service on a serial port that answers nothing."""
    return service(
        "uc2",
        UC2_PREFIX,
        "redsun_mimir.services.uc2_controller",
        UC2_READY,
        "--port",
        "loop://",
    )


@pytest.fixture
async def mm_stage(stage_service: Service) -> AsyncGenerator[MMStage, None]:
    """Return an ``MMStage`` connected to the stage service."""
    device = MMStage(stage_service.prefix, name="XY")
    await device.connect(timeout=CONNECT_TIMEOUT)
    yield device


@pytest.fixture
async def mm_camera(
    camera_service: Service, tmp_path: Path
) -> AsyncGenerator[MMCamera, None]:
    """Return an ``MMCamera`` connected to the camera service."""
    device = MMCamera(
        camera_service.prefix,
        path_provider=SessionPathProvider(base_dir=tmp_path, session="test"),
        name="camera1",
    )
    await device.connect(timeout=CONNECT_TIMEOUT)
    yield device


@pytest.fixture
async def mock_led() -> MockLightDevice:
    """Mock LED device with a narrow intensity range."""
    device = MockLightDevice("led", wavelength=450, range=(0.0, 1.0))
    await device.connect(mock=True)
    return device


@pytest.fixture
async def mock_laser() -> MockLightDevice:
    """Mock laser device with a wide intensity range."""
    device = MockLightDevice("laser", wavelength=650, range=(0.0, 100.0))
    await device.connect(mock=True)
    return device


@pytest.fixture
async def mock_binary_led() -> MockLightDevice:
    """Mock LED device that is on/off only."""
    device = MockLightDevice("binary_led", wavelength=300, binary=True)
    await device.connect(mock=True)
    return device
