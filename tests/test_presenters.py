"""Tests for redsun_mimir presenters."""

from __future__ import annotations

import asyncio
import json
import threading
from concurrent.futures import Future
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

import bluesky.plan_stubs as bps
import numpy as np
import pytest
from bluesky.run_engine import RunEngineResult
from bluesky.simulators import RunEngineSimulator
from ophyd_async.core import soft_signal_rw
from redsun.aio import run_coro
from redsun.engine import Deferrals, RunEngine
from redsun.engine.actions import ActionState
from redsun.path_provider import SessionPathProvider
from redsun.presenter import AcquisitionPresenter

from redsun_mimir.common import LIVE_VIEW_STREAM, MEDIAN_SCAN_STREAM, Roi
from redsun_mimir.plans import capture
from redsun_mimir.presenter.detector import DetectorPresenter
from redsun_mimir.presenter.median import MedianPresenter
from redsun_mimir.protocols import (
    DescribesDetectors,
    DetectorProtocol,
)
from tests.conftest import FakeDetector, FakeFlyer, FakeXYStage

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from bluesky.utils import Msg, MsgGenerator
    from event_model.documents import (
        Event,
        EventDescriptor,
        RunStop,
    )
    from ophyd_async.core import SignalRW


def root_attributes(store: Path) -> dict[str, Any]:
    """Return the attributes a Zarr v3 array or group at *store* carries."""
    attributes: dict[str, Any] = json.loads((store / "zarr.json").read_text())[
        "attributes"
    ]
    return attributes


async def set_roi(detector: DetectorProtocol, roi: tuple[int, int, int, int]) -> None:
    """Crop *detector* to *roi*, given as ``x, y, width, height``."""
    await detector.roi.set(str(Roi(*roi)))


@dataclass
class _MedianSource:
    """Minimal stand-in for a device MedianPresenter can track.

    Only ``buffer``, a named signal, is inspected.
    """

    buffer: SignalRW[np.ndarray]


def simulate_capture(plan: MsgGenerator[Any], written: int = 5) -> list[Msg]:
    """Run *plan* in a simulator answering waits as done and indices as *written*."""

    def index(msg: Msg) -> list[Future[int]]:
        future: Future[int] = Future()
        future.set_result(written)
        return [future]

    simulator = RunEngineSimulator()
    simulator.add_handler("wait", lambda msg: True)
    simulator.add_handler("wait_for", index)
    messages: list[Msg] = simulator.simulate_plan(plan)
    return messages


class TestMedianPresenter:
    """Tests for the document-driven MedianPresenter."""

    @staticmethod
    def capture(presenter: MedianPresenter, store: Path, scan_run: str | None) -> None:
        """Run a capture: a run of its own naming ``cam`` and its *store*, then its stop."""
        presenter(
            "start",
            {
                "uid": "capture",
                "time": 0.0,
                "purpose": "capture",
                "parent": "outer",
                "median_scan": scan_run,
            },
        )
        presenter(
            "descriptor",
            {
                "uid": "capture-desc",
                "run_start": "capture",
                "name": "live_stream",
                "data_keys": {
                    "cam": {
                        "source": store.as_uri(),
                        "dtype": "array",
                        "dtype_numpy": "<u2",
                        "shape": [1, 4, 4],
                        "external": "STREAM:",
                    }
                },
            },
        )
        presenter(
            "stream_resource",
            {
                "uid": "capture-res",
                "run_start": "capture",
                "data_key": "cam",
                "mimetype": "application/x-zarr",
                "uri": store.as_uri(),
                "parameters": {},
            },
        )
        presenter(
            "stop",
            {
                "uid": "capture-stop",
                "run_start": "capture",
                "time": 1.0,
                "exit_status": "success",
            },
        )

    @staticmethod
    def scan_uid(result: RunEngineResult | tuple[str, ...]) -> str:
        """Return the uid of the one run *result* carries."""
        uids = result.run_start_uids if isinstance(result, RunEngineResult) else result
        (uid,) = uids
        return uid

    @staticmethod
    def scan(
        buf: SignalRW[np.ndarray],
        frames: list[np.ndarray],
        motor: FakeXYStage | None = None,
    ) -> MsgGenerator[None]:
        """Run a square scan: the frames on the median stream, then its stop.

        With *motor*, its ``x`` axis steps by 5 before each frame and both axes
        are read into the frame's event.
        """
        readables: list[Any] = [buf] if motor is None else [buf, motor]
        yield from bps.open_run()
        yield from bps.declare_stream(*readables, name=MEDIAN_SCAN_STREAM)
        for frame in frames:
            if motor is not None:
                yield from bps.mvr(motor.axis["x"], 5.0)
            yield from bps.abs_set(buf, frame, wait=True)
            yield from bps.trigger_and_read(readables, name=MEDIAN_SCAN_STREAM)
        yield from bps.close_run()

    async def test_document_flow_computes_writes_and_emits_median(
        self, tmp_path: Path, motor_stage: FakeXYStage
    ) -> None:
        """Emit the median once and write the stack, with its positions, to the capture's store."""
        frames = [np.full((4, 4), i, dtype="uint16") for i in range(3)]
        store = tmp_path / "acquisition.zarr"
        buf = soft_signal_rw(np.ndarray, initial_value=frames[0], name="cam-buffer")
        devices: dict[str, Any] = {"cam": _MedianSource(buffer=buf)}
        presenter = MedianPresenter("median_presenter", sources=devices)
        received: list[dict[str, Any]] = []
        presenter.frames.median.connect(received.append)
        engine = RunEngine()
        engine.subscribe(presenter)

        presenter("start", {"uid": "outer", "time": 0.0})
        scan_run = self.scan_uid(
            engine(self.scan(buf, frames, motor_stage)).result(timeout=30)
        )
        self.capture(presenter, store, scan_run)

        expected = np.median(np.stack(frames), axis=0).astype("uint16")
        np.testing.assert_array_equal(presenter.medians["cam-buffer"], expected)
        assert len(received) == 1
        emitted_reading = next(iter(received[0].values()))
        np.testing.assert_array_equal(emitted_reading["value"], expected)
        written = json.loads((store / "cam_scan" / "zarr.json").read_text())
        assert written["shape"] == [3, 4, 4]
        assert root_attributes(store / "cam_scan")["derived_from"] == "cam"
        assert root_attributes(store / "cam_scan")["stream"] == MEDIAN_SCAN_STREAM
        assert root_attributes(store / "cam_scan")["scan_run"] == scan_run
        assert root_attributes(store / "cam_scan")["positions"] == [
            {
                "frame_id": 1,
                "axes": {"xystage-axis-x": 5.0, "xystage-axis-y": 0.0},
            },
            {
                "frame_id": 2,
                "axes": {"xystage-axis-x": 10.0, "xystage-axis-y": 0.0},
            },
            {
                "frame_id": 3,
                "axes": {"xystage-axis-x": 15.0, "xystage-axis-y": 0.0},
            },
        ]
        assert root_attributes(store / "cam_scan")["redsun"]["run_start"] == "capture"

    async def test_a_capture_before_the_scan_gets_no_stack(
        self, tmp_path: Path
    ) -> None:
        """Write no stack for a capture with no scan behind it."""
        frames = [np.full((4, 4), i, dtype="uint16") for i in range(3)]
        store = tmp_path / "acquisition.zarr"
        buf = soft_signal_rw(np.ndarray, initial_value=frames[0], name="cam-buffer")
        devices: dict[str, Any] = {"cam": _MedianSource(buffer=buf)}
        presenter = MedianPresenter("median_presenter", sources=devices)
        engine = RunEngine()
        engine.subscribe(presenter)

        presenter("start", {"uid": "outer", "time": 0.0})
        self.capture(presenter, store, None)
        assert not store.exists()
        scan_run = self.scan_uid(engine(self.scan(buf, frames)).result(timeout=30))
        self.capture(presenter, tmp_path / "second.zarr", scan_run)

        assert not store.exists()
        written = json.loads(
            (tmp_path / "second.zarr" / "cam_scan" / "zarr.json").read_text()
        )
        assert written["shape"] == [3, 4, 4]

    @pytest.mark.parametrize(
        ("captured", "ending", "warned"),
        [
            (False, "shutdown", True),
            (False, "next plan", True),
            (True, "shutdown", False),
            (True, "next plan", False),
        ],
    )
    async def test_a_scan_stack_never_written_is_warned_about(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        captured: bool,
        ending: str,
        warned: bool,
    ) -> None:
        """Warn when a scan stack is dropped unwritten, at shutdown or the next plan, and not once written."""
        frames = [np.full((4, 4), i, dtype="uint16") for i in range(3)]
        buf = soft_signal_rw(np.ndarray, initial_value=frames[0], name="cam-buffer")
        devices: dict[str, Any] = {"cam": _MedianSource(buffer=buf)}
        presenter = MedianPresenter("median_presenter", sources=devices)
        engine = RunEngine()
        engine.subscribe(presenter)

        presenter("start", {"uid": "outer", "time": 0.0})
        scan_run = self.scan_uid(engine(self.scan(buf, frames)).result(timeout=30))
        if captured:
            self.capture(presenter, tmp_path / "acquisition.zarr", scan_run)
        if ending == "shutdown":
            presenter.shutdown()
        else:
            presenter.clear_medians("live_median_scan")

        dropped = [
            record
            for record in caplog.records
            if record.levelname == "WARNING" and "never written" in record.getMessage()
        ]
        assert bool(dropped) is warned

    async def test_shutdown_closes_a_store_the_run_left_open(
        self, tmp_path: Path
    ) -> None:
        """Close at shutdown a store a capture left open, so its stack is readable."""
        frames = [np.full((4, 4), i, dtype="uint16") for i in range(3)]
        store = tmp_path / "acquisition.zarr"
        buf = soft_signal_rw(np.ndarray, initial_value=frames[0], name="cam-buffer")
        devices: dict[str, Any] = {"cam": _MedianSource(buffer=buf)}
        presenter = MedianPresenter("median_presenter", sources=devices)
        engine = RunEngine()
        engine.subscribe(presenter)
        presenter("start", {"uid": "outer", "time": 0.0})
        scan_run = self.scan_uid(engine(self.scan(buf, frames)).result(timeout=30))
        presenter("start", {"uid": "capture", "time": 0.0, "median_scan": scan_run})
        presenter(
            "descriptor",
            {
                "uid": "capture-desc",
                "run_start": "capture",
                "name": "live_stream",
                "data_keys": {
                    "cam": {
                        "source": store.as_uri(),
                        "dtype": "array",
                        "dtype_numpy": "<u2",
                        "shape": [1, 4, 4],
                        "external": "STREAM:",
                    }
                },
            },
        )
        presenter(
            "stream_resource",
            {
                "uid": "capture-res",
                "run_start": "capture",
                "data_key": "cam",
                "mimetype": "application/x-zarr",
                "uri": store.as_uri(),
                "parameters": {},
            },
        )

        presenter.shutdown()

        assert json.loads((store / "cam_scan" / "zarr.json").read_text())["shape"] == [
            3,
            4,
            4,
        ]

    async def test_live_frames_are_divided_by_the_cached_median(self) -> None:
        """Divide live frames by the cached median and publish them as their own layer."""
        buf = soft_signal_rw(
            np.ndarray,
            initial_value=np.zeros((4, 4), dtype="uint16"),
            name="cam-buffer",
        )
        devices: dict[str, Any] = {"cam": _MedianSource(buffer=buf)}
        presenter = MedianPresenter("median_presenter", sources=devices)

        filtered: list[dict[str, Any]] = []
        presenter.frames.filtered.connect(filtered.append)

        # scan phase: a constant background of 2
        presenter.descriptor(
            cast(
                "EventDescriptor",
                {
                    "uid": "scan-desc",
                    "run_start": "scan-run",
                    "name": MEDIAN_SCAN_STREAM,
                    "data_keys": {"cam-buffer": {"shape": [4, 4]}},
                },
            )
        )
        background = np.full((4, 4), 2, dtype="uint16")
        for seq_num in range(1, 4):
            presenter.event(
                cast(
                    "Event",
                    {
                        "descriptor": "scan-desc",
                        "seq_num": seq_num,
                        "time": 0.0,
                        "data": {"cam-buffer": background},
                    },
                )
            )
        presenter.stop(
            cast("RunStop", {"run_start": "scan-run", "time": 1.0, "uid": "stop-1"})
        )

        assert filtered == [], "no live frame has arrived yet"

        # live phase: frames on any other stream get corrected
        presenter.descriptor(
            cast(
                "EventDescriptor",
                {
                    "uid": "live-desc",
                    "run_start": "live-run",
                    "name": LIVE_VIEW_STREAM,
                    "data_keys": {"cam-buffer": {"shape": [4, 4]}},
                },
            )
        )
        presenter.event(
            cast(
                "Event",
                {
                    "descriptor": "live-desc",
                    "time": 2.0,
                    "data": {"cam-buffer": np.full((4, 4), 8, dtype="uint16")},
                },
            )
        )

        assert len(filtered) == 1
        # keyed for its own viewer layer, distinct from the raw one
        assert set(filtered[0]) == {"cam_filtered"}
        np.testing.assert_allclose(
            filtered[0]["cam_filtered"]["value"], np.full((4, 4), 4.0)
        )

    async def test_monitor_drives_the_correction_through_the_run_engine(self) -> None:
        """Correct monitored live frames on a real engine after a scan."""
        buf = soft_signal_rw(
            np.ndarray,
            initial_value=np.zeros((4, 4), dtype="uint16"),
            name="cam-buffer",
        )
        devices: dict[str, Any] = {"cam": _MedianSource(buffer=buf)}
        presenter = MedianPresenter("median_presenter", sources=devices)

        filtered: list[dict[str, Any]] = []
        presenter.frames.filtered.connect(filtered.append)

        engine = RunEngine()
        engine.subscribe(presenter)

        background = np.full((4, 4), 2, dtype="uint16")

        def scan() -> MsgGenerator[None]:
            yield from bps.open_run()
            yield from bps.declare_stream(buf, name=MEDIAN_SCAN_STREAM)
            for _ in range(3):
                yield from bps.abs_set(buf, background, wait=True)
                yield from bps.trigger_and_read([buf], name=MEDIAN_SCAN_STREAM)
            yield from bps.close_run()

        def live() -> MsgGenerator[None]:
            yield from bps.open_run()
            yield from bps.monitor(buf, name=LIVE_VIEW_STREAM)
            yield from bps.abs_set(buf, np.full((4, 4), 8, dtype="uint16"), wait=True)
            yield from bps.sleep(0.05)
            yield from bps.unmonitor(buf)
            yield from bps.close_run()

        engine(scan()).result(timeout=30)
        np.testing.assert_array_equal(presenter.medians["cam-buffer"], background)

        engine(live()).result(timeout=30)

        assert filtered, "bps.monitor produced no corrected frames"
        values = [entry["cam_filtered"]["value"] for entry in filtered]
        # the last monitored frame is the 8 written above, divided by 2
        np.testing.assert_allclose(values[-1], np.full((4, 4), 4.0))

    async def test_live_frames_without_a_median_are_not_emitted(self) -> None:
        """Emit no corrected frame before any scan."""
        buf = soft_signal_rw(
            np.ndarray,
            initial_value=np.zeros((4, 4), dtype="uint16"),
            name="cam-buffer",
        )
        devices: dict[str, Any] = {"cam": _MedianSource(buffer=buf)}
        presenter = MedianPresenter("median_presenter", sources=devices)

        filtered: list[dict[str, Any]] = []
        presenter.frames.filtered.connect(filtered.append)

        presenter.descriptor(
            cast(
                "EventDescriptor",
                {
                    "uid": "live-desc",
                    "run_start": "live-run",
                    "name": LIVE_VIEW_STREAM,
                    "data_keys": {"cam-buffer": {"shape": [4, 4]}},
                },
            )
        )
        presenter.event(
            cast(
                "Event",
                {
                    "descriptor": "live-desc",
                    "time": 0.0,
                    "data": {"cam-buffer": np.full((4, 4), 8, dtype="uint16")},
                },
            )
        )

        assert filtered == []

    async def test_descriptor_ignores_unrelated_sources(self) -> None:
        """Ignore a stream carrying no tracked buffer."""
        buf = soft_signal_rw(
            np.ndarray,
            initial_value=np.zeros((4, 4), dtype="uint16"),
            name="cam-buffer",
        )
        other = soft_signal_rw(float, initial_value=0.0, name="other-signal")
        devices: dict[str, Any] = {"cam": _MedianSource(buffer=buf)}
        presenter = MedianPresenter("median_presenter", sources=devices)

        received: list[dict[str, Any]] = []
        presenter.frames.median.connect(received.append)

        engine = RunEngine()
        engine.subscribe(presenter)

        def plan() -> MsgGenerator[None]:
            yield from bps.open_run()
            yield from bps.declare_stream(other, name="unrelated")
            yield from bps.trigger_and_read([other], name="unrelated")
            yield from bps.close_run()

        engine(plan()).result(timeout=30)

        assert received == []
        assert presenter.medians == {}

    def test_the_square_scan_takes_a_frame_before_every_move(
        self, fake_detector: FakeDetector, motor_stage: FakeXYStage
    ) -> None:
        """Take a frame before every move, so the stack starts where the motor stands."""
        presenter = MedianPresenter("median_ctrl", sources={})
        simulator = RunEngineSimulator()
        simulator.add_handler("locate", lambda msg: {"readback": 0.0, "setpoint": 0.0})

        messages = simulator.simulate_plan(
            presenter.square_scan([fake_detector], motor_stage, 5.0, 1)
        )

        assert [
            (msg.command, getattr(msg.obj, "name", None))
            for msg in messages
            if msg.command in {"trigger", "save", "set"}
        ] == [
            ("trigger", "cam"),
            ("save", None),
            ("set", "xystage-axis-x"),
            ("trigger", "cam"),
            ("save", None),
            ("set", "xystage-axis-y"),
            ("trigger", "cam"),
            ("save", None),
            ("set", "xystage-axis-x"),
            ("trigger", "cam"),
            ("save", None),
            ("set", "xystage-axis-y"),
        ]

    def test_the_square_scan_reports_each_frame_it_takes(
        self, fake_detector: FakeDetector, motor_stage: FakeXYStage
    ) -> None:
        """Report each frame of the scan against the whole square, inside its run."""
        presenter = MedianPresenter("median_ctrl", sources={})
        simulator = RunEngineSimulator()
        simulator.add_handler("locate", lambda msg: {"readback": 0.0, "setpoint": 0.0})

        messages = simulator.simulate_plan(
            presenter.square_scan([fake_detector], motor_stage, 5.0, 2)
        )

        commands = [msg.command for msg in messages]
        updates = [
            (msg.kwargs["current"], msg.kwargs["target"], msg.kwargs["unit"])
            for msg in messages
            if msg.command == "update_progress" and not msg.kwargs["done"]
        ]
        assert updates == [(frame, 8, "frames") for frame in range(1, 9)]
        assert (
            commands.index("open_run")
            < commands.index("declare_progress")
            < commands.index("trigger")
        )
        finished = len(commands) - 1 - commands[::-1].index("update_progress")
        assert messages[finished].kwargs["done"]
        assert finished < commands.index("close_run")


class TestDetectorPresenter:
    """Tests for DetectorPresenter."""

    @pytest.fixture
    def controller(
        self, fake_detector: FakeDetector
    ) -> Generator[DetectorPresenter, None, None]:
        yield DetectorPresenter(
            "det_ctrl", detectors={fake_detector.name: fake_detector}
        )

    def test_describes_its_detectors(self, controller: DetectorPresenter) -> None:
        """Describe, read and lay out every detector."""
        assert isinstance(controller, DescribesDetectors)
        assert "cam" in controller.detector_layer_specs()
        assert "cam-exposure" in controller.detector_readings()

    def test_a_setting_the_presenter_cannot_write_is_described_read_only(
        self, controller: DetectorPresenter
    ) -> None:
        """Append `:readonly` to the source of a setting the presenter cannot write."""
        described = controller.detector_descriptors()

        assert described["cam-sensor_size"]["source"].endswith(":readonly")
        assert not described["cam-pixel_dtype"]["source"].endswith(":readonly")
        assert not described["cam-exposure"]["source"].endswith(":readonly")
        assert not described["cam-roi"]["source"].endswith(":readonly")

    def test_live_events_are_forwarded_raw(
        self, controller: DetectorPresenter, fake_detector: FakeDetector
    ) -> None:
        """Forward the frames of a live event unmodified."""
        key = fake_detector.buffer.name
        received: list[dict[str, Any]] = []
        controller.sig_new_data.connect(received.append)

        controller.descriptor(
            cast(
                "EventDescriptor",
                {"uid": "desc-1", "run_start": "run-1", "data_keys": {key: {}}},
            )
        )
        frame = np.full((4, 4), 8.0, dtype=np.float32)
        controller.event(
            cast(
                "Event",
                {"descriptor": "desc-1", "time": 0.0, "data": {key: frame}},
            )
        )

        assert len(received) == 1
        np.testing.assert_array_equal(received[0][key]["value"], frame)
        assert received[0][f"{fake_detector.name}-roi"]["value"] == Roi.parse(
            run_coro(fake_detector.roi.get_value())
        )

    def test_a_frame_is_forwarded_with_the_roi_it_was_taken_with(
        self, fake_detector: FakeDetector
    ) -> None:
        """Forward a frame with the ROI it was taken with."""
        presenter = DetectorPresenter("det_ctrl", detectors={"cam": fake_detector})
        received: list[dict[str, Any]] = []
        presenter.sig_new_data.connect(received.append)
        presenter.descriptor(
            cast(
                "EventDescriptor",
                {
                    "uid": "desc-1",
                    "run_start": "run-1",
                    "data_keys": {"cam-buffer": {}},
                },
            )
        )
        event = cast(
            "Event",
            {
                "descriptor": "desc-1",
                "time": 0.0,
                "data": {"cam-buffer": np.zeros((2, 3))},
            },
        )

        run_coro(set_roi(fake_detector, (1, 1, 3, 2)))
        presenter.event(event)

        assert received[-1]["cam-roi"]["value"] == Roi(1, 1, 3, 2)
        assert list(received[-1]) == ["cam-roi", "cam-buffer"]

    def test_shutdown_stops_following_the_rois(
        self, fake_detector: FakeDetector
    ) -> None:
        """Stop following the ROIs at shutdown."""
        presenter = DetectorPresenter("det_ctrl", detectors={"cam": fake_detector})
        received: list[dict[str, Any]] = []
        presenter.sig_new_data.connect(received.append)
        presenter.descriptor(
            cast(
                "EventDescriptor",
                {
                    "uid": "desc-1",
                    "run_start": "run-1",
                    "data_keys": {"cam-buffer": {}},
                },
            )
        )
        event = cast(
            "Event",
            {
                "descriptor": "desc-1",
                "time": 0.0,
                "data": {"cam-buffer": np.zeros((2, 3))},
            },
        )

        presenter.shutdown()
        run_coro(set_roi(fake_detector, (1, 1, 3, 2)))
        presenter.event(event)

        assert received[-1]["cam-roi"]["value"] == Roi(0, 0, 6, 4)

    def test_a_layer_is_the_size_of_the_sensor_whatever_the_roi(
        self, fake_detector: FakeDetector
    ) -> None:
        """Size a layer as the whole sensor, whatever the ROI."""
        run_coro(set_roi(fake_detector, (1, 1, 3, 2)))

        specs = DetectorPresenter(
            "det_ctrl", detectors={"cam": fake_detector}
        ).detector_layer_specs()

        assert specs["cam"]["shape"] == (4, 6)

    def test_events_from_unknown_streams_are_ignored(
        self, controller: DetectorPresenter
    ) -> None:
        """Ignore an event whose descriptor was never routed."""
        received: list[dict[str, Any]] = []
        controller.sig_new_data.connect(received.append)

        controller.event(
            cast(
                "Event",
                {"descriptor": "never-seen", "time": 0.0, "data": {"x": 1.0}},
            )
        )

        assert received == []

    async def test_a_roi_change_during_a_plan_lands_between_two_messages(
        self, fake_detector: FakeDetector
    ) -> None:
        """Apply a ROI asked for during a plan between two of its messages."""
        engine = RunEngine()
        presenter = DetectorPresenter("det_ctrl", detectors={"cam": fake_detector})
        presenter.setup(Deferrals(engine))
        announced: list[tuple[str, str, Any]] = []
        presenter.sig_new_configuration.connect(lambda *args: announced.append(args))
        # a message the test keeps waiting, so the change cannot be applied before the
        # assertions on whatever machine runs them
        release = asyncio.Event()
        entered = threading.Event()

        async def hold() -> None:
            entered.set()
            await release.wait()

        def blocking_plan() -> MsgGenerator[None]:
            yield from bps.wait_for([hold])

        future = engine(blocking_plan())
        assert await asyncio.to_thread(entered.wait, 5)

        await presenter.set("cam", "roi", "1,1,3,2")
        await presenter.set("cam", "exposure", 5.0)

        assert await fake_detector.roi.get_value() == "0,0,6,4"
        assert await fake_detector.exposure.get_value() == 5.0
        engine.loop.call_soon_threadsafe(release.set)
        future.result(timeout=5)
        assert await fake_detector.roi.get_value() == "1,1,3,2"
        assert ("cam", "cam-roi", "1,1,3,2") in announced

    async def test_a_refused_setting_is_logged_and_not_announced(
        self,
        controller: DetectorPresenter,
        fake_detector: FakeDetector,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Log a setting the device refuses, and announce nothing."""
        received: list[tuple[str, str, Any]] = []
        controller.sig_new_configuration.connect(
            lambda d, k, v: received.append((d, k, v))
        )

        await controller.set(fake_detector.name, "exposure", "not a number")

        assert received == []
        assert "Failed to set" in caplog.text

    async def test_set_exposure_emits_new_configuration(
        self, controller: DetectorPresenter, fake_detector: FakeDetector
    ) -> None:
        """Apply a setting and announce its new value."""
        received: list[tuple[str, str, Any]] = []
        controller.sig_new_configuration.connect(
            lambda d, k, v: received.append((d, k, v))
        )
        await controller.set(fake_detector.name, "exposure", 50.0)

        assert received
        assert received[0][0] == fake_detector.name
        assert run_coro(fake_detector.exposure.get_value()) == pytest.approx(50.0)


class TestLiveStream:
    """The detector presenter's plan, run by redsun's acquisition presenter."""

    def test_live_stream_offers_its_action_and_stops(
        self, fake_flyer: FakeFlyer, tmp_path: Path
    ) -> None:
        """Run `live_stream`, offer its stream action, and end it when stopped."""
        detector = DetectorPresenter("det_ctrl", detectors={"cam": fake_flyer})
        acquisition = AcquisitionPresenter("acq_ctrl", devices={"cam": fake_flyer})
        acquisition.setup(
            {"det_ctrl": detector}, {}, SessionPathProvider(base_dir=tmp_path)
        )
        offered, ended = threading.Event(), threading.Event()
        acquisition.sig_action_changed.connect(
            lambda action, state: (
                offered.set()
                if (action, state) == ("stream", ActionState.OFFERED)
                else None
            )
        )
        acquisition.sig_plan_done.connect(
            lambda plan: ended.set() if plan == "live_stream" else None
        )
        try:
            acquisition.launch(
                "live_stream",
                {"detectors": ["cam"], "frames": 1, "write_forever": False},
            )
            assert offered.wait(10)
            acquisition.stop()
            assert ended.wait(10)
        finally:
            acquisition.shutdown()


class TestCapture:
    """Tests for the plan stub flying detectors to disk."""

    def test_an_open_capture_collects_while_it_waits(
        self, fake_flyer: FakeFlyer
    ) -> None:
        """Collect what was written while the window waits, not only at its close."""

        def waiting() -> MsgGenerator[None]:
            for _ in range(3):
                yield from bps.sleep(0.25)

        messages = simulate_capture(
            capture([fake_flyer], "stream", parent="live", until=waiting())
        )

        commands = [msg.command for msg in messages]
        window = commands[commands.index("kickoff") : commands.index("complete")]
        assert "collect" in window

    def test_a_bounded_capture_follows_its_detector(
        self, fake_flyer: FakeFlyer
    ) -> None:
        """Follow each detector's completion with a progress scope named after it."""
        messages = simulate_capture(capture([fake_flyer], "stream", parent="live"))

        commands = [msg.command for msg in messages]
        followed = messages[commands.index("monitor_progress")]
        assert commands.index("complete") < commands.index("monitor_progress")
        assert followed.kwargs["name"] == "cam"
        assert "declare_progress" not in commands

    def test_an_open_capture_counts_the_frames_written(
        self, fake_flyer: FakeFlyer
    ) -> None:
        """Count the frames written after each collect, and close the count before completing."""

        def waiting() -> MsgGenerator[None]:
            for _ in range(3):
                yield from bps.sleep(0.25)

        messages = simulate_capture(
            capture([fake_flyer], "stream", parent="live", until=waiting()),
            written=7,
        )

        progress = [
            (msg.command, msg.kwargs.get("current"), msg.kwargs.get("done"))
            for msg in messages
            if msg.command in {"declare_progress", "update_progress", "complete"}
        ]
        assert progress == [
            ("declare_progress", None, None),
            ("update_progress", 7, False),
            ("update_progress", None, True),
            ("complete", None, None),
        ]
        assert {
            msg.kwargs["unit"]
            for msg in messages
            if msg.command == "update_progress" and not msg.kwargs["done"]
        } == {"frames"}
