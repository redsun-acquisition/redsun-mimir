"""Tests for the microscope simulated device implementations."""

from __future__ import annotations

import numpy as np
import pytest

from redsun_mimir.device.microscope._devices import (
    SimulatedCameraDevice,
    SimulatedLightDevice,
    SimulatedStageDevice,
    _stage_callbacks,
    _stage_registry,
)
from redsun_mimir.protocols import DetectorProtocol, LightProtocol, MotorProtocol


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def stage(request: pytest.FixtureRequest) -> SimulatedStageDevice:
    """XYZ simulated stage with unit step sizes and symmetric limits."""
    name = getattr(request, "param", "sim_stage")
    return SimulatedStageDevice(
        name,
        axis=["x", "y", "z"],
        step_sizes={"x": 1.0, "y": 1.0, "z": 1.0},
        limits={"x": (0.0, 200.0), "y": (0.0, 200.0), "z": (-10.0, 10.0)},
    )


@pytest.fixture
def camera(request: pytest.FixtureRequest) -> SimulatedCameraDevice:
    """Camera without a linked stage (standalone mode)."""
    name = getattr(request, "param", "sim_camera")
    return SimulatedCameraDevice(name, sensor_shape=(64, 64))


@pytest.fixture
def light() -> SimulatedLightDevice:
    """Simulated 532 nm laser light source."""
    return SimulatedLightDevice(
        "sim_light",
        wavelength=532,
        intensity_range=(0, 100),
        egu="mW",
        step_size=1,
    )


def _enable(cam: SimulatedCameraDevice) -> None:
    """Enable acquisition on a camera and mark it as acquiring."""
    cam.enable()
    cam._do_enable()
    cam._acquiring = True


# ---------------------------------------------------------------------------
# SimulatedStageDevice
# ---------------------------------------------------------------------------


class TestSimulatedStageDevice:
    """Tests for SimulatedStageDevice."""

    def test_instantiation(self, stage: SimulatedStageDevice) -> None:
        """Device initialises with correct name and attributes."""
        assert stage.name == "sim_stage"
        assert stage.axis == ["x", "y", "z"]
        assert stage.egu == "mm"

    def test_implements_protocol(self, stage: SimulatedStageDevice) -> None:
        """SimulatedStageDevice satisfies the MotorProtocol runtime check."""
        assert isinstance(stage, MotorProtocol)

    def test_registers_in_stage_registry(self, stage: SimulatedStageDevice) -> None:
        """Stage registers itself in the module-level registry on construction."""
        assert stage.name in _stage_registry
        assert _stage_registry[stage.name] is stage

    def test_missing_limits_raises(self) -> None:
        """Omitting limits raises ValueError."""
        with pytest.raises(ValueError, match="requires limits"):
            SimulatedStageDevice(
                "no_limits",
                axis=["x"],
                step_sizes={"x": 1.0},
            )

    def test_locate_returns_active_axis_position(
        self, stage: SimulatedStageDevice
    ) -> None:
        """locate() returns setpoint and readback for the active (first) axis."""
        loc = stage.locate()
        assert "setpoint" in loc
        assert "readback" in loc
        assert loc["setpoint"] == loc["readback"]

    def test_set_moves_active_axis(self, stage: SimulatedStageDevice) -> None:
        """set() moves the active axis to the target position."""
        status = stage.set(50.0)
        status.wait(timeout=1.0)
        assert status.success
        assert stage.locate()["readback"] == pytest.approx(50.0)

    def test_set_invalid_value_fails(self, stage: SimulatedStageDevice) -> None:
        """set() with a non-numeric value marks status as failed."""
        status = stage.set("not_a_number")
        with pytest.raises(ValueError):
            status.wait(timeout=1.0)
        assert not status.success

    def test_set_axis_prop_switches_active_axis(
        self, stage: SimulatedStageDevice
    ) -> None:
        """prop='axis' switches which axis subsequent set() calls target."""
        status = stage.set("y", prop="axis")
        status.wait(timeout=1.0)
        assert status.success
        assert stage._active_axis == "y"

    def test_set_step_size_prop_updates_step(
        self, stage: SimulatedStageDevice
    ) -> None:
        """prop='step_size' updates the step size for the active axis."""
        status = stage.set(2.5, prop="step_size")
        status.wait(timeout=1.0)
        assert status.success
        assert stage.step_sizes["x"] == pytest.approx(2.5)

    def test_set_unknown_prop_fails(self, stage: SimulatedStageDevice) -> None:
        """An unrecognised prop name marks status as failed."""
        status = stage.set(1.0, prop="unknown")
        with pytest.raises(ValueError):
            status.wait(timeout=1.0)
        assert not status.success

    def test_move_to_clamps_at_limits(self, stage: SimulatedStageDevice) -> None:
        """Moving beyond axis limits clamps to the limit (microscope behaviour)."""
        stage.move_to({"x": 9999.0})
        assert stage.position["x"] == pytest.approx(200.0)

    def test_describe_configuration_keys(self, stage: SimulatedStageDevice) -> None:
        """describe_configuration() contains egu, axis and per-axis step-size keys."""
        desc = stage.describe_configuration()
        assert "sim_stage-egu" in desc
        assert "sim_stage-axis" in desc
        for ax in ["x", "y", "z"]:
            assert f"sim_stage-step_size-{ax}" in desc

    def test_read_configuration_values(self, stage: SimulatedStageDevice) -> None:
        """read_configuration() returns correct egu, axis and step-size values."""
        cfg = stage.read_configuration()
        assert cfg["sim_stage-egu"]["value"] == "mm"
        assert cfg["sim_stage-axis"]["value"] == ["x", "y", "z"]
        for ax in ["x", "y", "z"]:
            assert cfg[f"sim_stage-step_size-{ax}"]["value"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# SimulatedLightDevice
# ---------------------------------------------------------------------------


class TestSimulatedLightDevice:
    """Tests for SimulatedLightDevice."""

    def test_instantiation(self, light: SimulatedLightDevice) -> None:
        """Device initialises with correct name and attributes."""
        assert light.name == "sim_light"
        assert light.wavelength == 532
        assert light.egu == "mW"
        assert light.intensity_range == (0, 100)

    def test_implements_protocol(self, light: SimulatedLightDevice) -> None:
        """SimulatedLightDevice satisfies the LightProtocol runtime check."""
        assert isinstance(light, LightProtocol)

    def test_binary_mode_raises(self) -> None:
        """Passing binary=True raises AttributeError."""
        with pytest.raises(AttributeError, match="binary"):
            SimulatedLightDevice(
                "bin_light",
                wavelength=450,
                binary=True,
                intensity_range=(0, 1),
            )

    def test_zero_intensity_range_raises(self) -> None:
        """intensity_range=(0, 0) raises AttributeError."""
        with pytest.raises(AttributeError, match="intensity range"):
            SimulatedLightDevice(
                "zero_light",
                wavelength=450,
                intensity_range=(0, 0),
            )

    def test_trigger_toggles_on_off(self, light: SimulatedLightDevice) -> None:
        """trigger() toggles the light on, then off."""
        assert not light.get_is_on()
        light.trigger().wait(timeout=1.0)
        assert light.get_is_on()
        light.trigger().wait(timeout=1.0)
        assert not light.get_is_on()

    def test_set_intensity(self, light: SimulatedLightDevice) -> None:
        """set() updates the intensity without error."""
        status = light.set(75.0)
        status.wait(timeout=1.0)
        assert status.success

    def test_set_invalid_value_fails(self, light: SimulatedLightDevice) -> None:
        """set() with a non-numeric value marks status as failed."""
        status = light.set("max")
        with pytest.raises(ValueError):
            status.wait(timeout=1.0)
        assert not status.success

    def test_set_with_prop_fails(self, light: SimulatedLightDevice) -> None:
        """Passing a prop kwarg marks status as failed (unsupported)."""
        status = light.set(10.0, prop="wavelength")
        with pytest.raises(RuntimeError):
            status.wait(timeout=1.0)
        assert not status.success

    def test_describe_uses_make_key(self, light: SimulatedLightDevice) -> None:
        """describe() keys follow the name-property convention."""
        desc = light.describe()
        assert "sim_light-intensity" in desc
        assert "sim_light-enabled" in desc

    def test_describe_source_is_data(self, light: SimulatedLightDevice) -> None:
        """describe() uses 'data' as source, consistent with other detectors."""
        desc = light.describe()
        assert desc["sim_light-intensity"]["source"] == "data"
        assert desc["sim_light-enabled"]["source"] == "data"

    def test_read_keys_match_describe(self, light: SimulatedLightDevice) -> None:
        """read() returns the same keys as describe()."""
        assert set(light.read().keys()) == set(light.describe().keys())

    def test_describe_configuration_keys(self, light: SimulatedLightDevice) -> None:
        """describe_configuration() contains all expected keys."""
        desc = light.describe_configuration()
        for key in ["wavelength", "binary", "egu", "intensity_range", "step_size"]:
            assert f"sim_light-{key}" in desc

    def test_describe_configuration_readonly(self, light: SimulatedLightDevice) -> None:
        """Configuration descriptors are marked readonly."""
        desc = light.describe_configuration()
        for key in desc:
            assert desc[key]["source"].endswith(":readonly"), (
                f"Expected {key!r} source to end with ':readonly'"
            )

    def test_read_configuration_values(self, light: SimulatedLightDevice) -> None:
        """read_configuration() returns correct values for all keys."""
        cfg = light.read_configuration()
        assert cfg["sim_light-wavelength"]["value"] == 532
        assert cfg["sim_light-egu"]["value"] == "mW"
        assert cfg["sim_light-intensity_range"]["value"] == [0, 100]
        assert cfg["sim_light-step_size"]["value"] == 1


# ---------------------------------------------------------------------------
# SimulatedCameraDevice — standalone (no stage)
# ---------------------------------------------------------------------------


class TestSimulatedCameraDeviceStandalone:
    """Tests for SimulatedCameraDevice without a linked stage."""

    def test_instantiation(self, camera: SimulatedCameraDevice) -> None:
        """Camera initialises with correct name and sensor shape."""
        assert camera.name == "sim_camera"
        assert camera.sensor_shape == (64, 64)

    def test_implements_protocol(self, camera: SimulatedCameraDevice) -> None:
        """SimulatedCameraDevice satisfies the DetectorProtocol runtime check."""
        assert isinstance(camera, DetectorProtocol)

    def test_no_stage_linked(self, camera: SimulatedCameraDevice) -> None:
        """Camera with stage_name=None has _stage_linked=False."""
        assert not camera._stage_linked

    def test_blank_frame_when_no_stage(self, camera: SimulatedCameraDevice) -> None:
        """_fetch_data() returns a blank uint16 frame when no stage is linked."""
        _enable(camera)
        camera._triggered = 1
        frame = camera._fetch_data()
        assert frame is not None
        assert frame.shape == (64, 64)
        assert frame.dtype == np.uint16
        assert np.all(frame == 0)

    def test_fetch_data_returns_none_when_not_acquiring(
        self, camera: SimulatedCameraDevice
    ) -> None:
        """_fetch_data() returns None when not acquiring."""
        frame = camera._fetch_data()
        assert frame is None

    def test_describe_keys_use_make_key(self, camera: SimulatedCameraDevice) -> None:
        """describe() keys follow the name-property convention."""
        desc = camera.describe()
        assert "sim_camera-buffer" in desc
        assert "sim_camera-roi" in desc

    def test_describe_source_is_data(self, camera: SimulatedCameraDevice) -> None:
        """describe() uses 'data' as source for buffer and roi."""
        desc = camera.describe()
        assert desc["sim_camera-buffer"]["source"] == "data"
        assert desc["sim_camera-roi"]["source"] == "data"

    def test_describe_buffer_shape(self, camera: SimulatedCameraDevice) -> None:
        """describe() reports the sensor shape for the buffer key."""
        desc = camera.describe()
        assert desc["sim_camera-buffer"]["shape"] == [1, 64, 64]

    def test_describe_configuration_contains_sensor_shape(
        self, camera: SimulatedCameraDevice
    ) -> None:
        """describe_configuration() includes a sensor_shape key."""
        assert "sim_camera-sensor_shape" in camera.describe_configuration()

    def test_read_configuration_sensor_shape_value(
        self, camera: SimulatedCameraDevice
    ) -> None:
        """read_configuration() reports the correct sensor shape."""
        cfg = camera.read_configuration()
        assert cfg["sim_camera-sensor_shape"]["value"] == [64, 64]

    def test_describe_collect_stream_key(self, camera: SimulatedCameraDevice) -> None:
        """describe_collect() uses the colon-separated streaming key convention."""
        desc = camera.describe_collect()
        assert "sim_camera:buffer:stream" in desc

    def test_describe_collect_external_stream(
        self, camera: SimulatedCameraDevice
    ) -> None:
        """describe_collect() marks the stream key as STREAM: external."""
        desc = camera.describe_collect()
        assert desc["sim_camera:buffer:stream"]["external"] == "STREAM:"

    def test_stage_and_unstage(self, camera: SimulatedCameraDevice) -> None:
        """stage() and unstage() both return successful statuses."""
        s = camera.stage()
        s.wait(timeout=2.0)
        assert s.success
        s = camera.unstage()
        s.wait(timeout=2.0)
        assert s.success

    def test_trigger_increments_sent(self, camera: SimulatedCameraDevice) -> None:
        """trigger() increments the internal sent counter."""
        _enable(camera)
        before = camera._sent
        camera.trigger()
        # give the camera one frame to process
        camera._triggered = 1
        camera._fetch_data()
        assert camera._sent == before + 1


# ---------------------------------------------------------------------------
# SimulatedCameraDevice — stage wiring (order-independent)
# ---------------------------------------------------------------------------


class TestSimulatedCameraDeviceStageWiring:
    """Tests for stage-aware imaging and the callback wiring mechanism."""

    def _make_stage(self, name: str = "wiring_stage") -> SimulatedStageDevice:
        return SimulatedStageDevice(
            name,
            axis=["x", "y", "z"],
            step_sizes={"x": 1.0, "y": 1.0, "z": 1.0},
            limits={"x": (0.0, 200.0), "y": (0.0, 200.0), "z": (-10.0, 10.0)},
        )

    def _make_camera(
        self, name: str = "wiring_cam", stage_name: str = "wiring_stage"
    ) -> SimulatedCameraDevice:
        return SimulatedCameraDevice(
            name,
            sensor_shape=(64, 64),
            stage_name=stage_name,
        )

    # --- stage-first ordering ---

    def test_stage_first_links_immediately(self) -> None:
        """Camera built after stage links immediately without registering a callback."""
        stage = self._make_stage("sf_stage")
        cam = self._make_camera("sf_cam", stage_name="sf_stage")
        assert cam._stage_linked
        assert "sf_stage" not in _stage_callbacks

    # --- camera-first ordering ---

    def test_camera_first_registers_callback(self) -> None:
        """Camera built before stage registers a pending callback."""
        cam = self._make_camera("cf_cam", stage_name="cf_stage")
        assert not cam._stage_linked
        assert "cf_stage" in _stage_callbacks
        assert len(_stage_callbacks["cf_stage"]) == 1

    def test_camera_first_links_when_stage_arrives(self) -> None:
        """Pending callback fires and links the camera when the stage is built."""
        cam = self._make_camera("cfl_cam", stage_name="cfl_stage")
        assert not cam._stage_linked
        self._make_stage("cfl_stage")
        assert cam._stage_linked
        assert "cfl_stage" not in _stage_callbacks

    # --- image behaviour ---

    def test_stage_aware_image_has_correct_shape_and_dtype(self) -> None:
        """_fetch_data() returns a uint16 frame at the sensor shape."""
        stage = self._make_stage("img_stage")
        cam = self._make_camera("img_cam", stage_name="img_stage")
        _enable(cam)
        cam._triggered = 1
        frame = cam._fetch_data()
        assert frame is not None
        assert frame.shape == (64, 64)
        assert frame.dtype == np.uint16

    def test_image_changes_with_stage_position(self) -> None:
        """Moving the stage produces a different image crop."""
        stage = self._make_stage("mv_stage")
        cam = self._make_camera("mv_cam", stage_name="mv_stage")
        _enable(cam)

        stage.move_to({"x": 10.0, "y": 10.0, "z": 0.0})
        cam._triggered = 1
        frame_a = cam._fetch_data()

        stage.move_to({"x": 190.0, "y": 190.0, "z": 0.0})
        cam._triggered = 1
        frame_b = cam._fetch_data()

        assert not np.array_equal(frame_a, frame_b), (
            "Images should differ after stage move"
        )

    def test_z_defocus_reduces_sharpness(self) -> None:
        """Increasing |Z| reduces image sharpness (higher Laplacian variance = sharper)."""
        import scipy.ndimage

        stage = self._make_stage("df_stage")
        cam = self._make_camera("df_cam", stage_name="df_stage")
        _enable(cam)

        stage.move_to({"x": 100.0, "y": 100.0, "z": 0.0})
        cam._triggered = 1
        sharp = cam._fetch_data()

        stage.move_to({"x": 100.0, "y": 100.0, "z": 10.0})
        cam._triggered = 1
        blurry = cam._fetch_data()

        def sharpness(img: np.ndarray) -> float:
            return float(scipy.ndimage.laplace(img.astype(np.float64)).var())

        assert sharpness(sharp) > sharpness(blurry), (
            "In-focus image should be sharper than out-of-focus image"
        )

    def test_stage_missing_z_axis_stays_unlinked(self) -> None:
        """Stage without z axis logs a warning and leaves camera unlinked."""
        SimulatedStageDevice(
            "no_z_stage",
            axis=["x", "y"],
            step_sizes={"x": 1.0, "y": 1.0},
            limits={"x": (0.0, 100.0), "y": (0.0, 100.0)},
        )
        cam = SimulatedCameraDevice(
            "no_z_cam", sensor_shape=(32, 32), stage_name="no_z_stage"
        )
        assert not cam._stage_linked

    def test_out_of_bounds_stage_position_returns_padded_frame(self) -> None:
        """Stage positioned beyond world-image edges returns a padded (partly zero) frame."""
        stage = self._make_stage("oob_stage")
        cam = self._make_camera("oob_cam", stage_name="oob_stage")
        _enable(cam)

        # Move far outside the mapped world-image area
        stage.move_to({"x": 0.0, "y": 0.0, "z": 0.0})
        cam._triggered = 1
        frame = cam._fetch_data()

        assert frame is not None
        assert frame.shape == (64, 64)
        # At least some pixels should be zero (padding)
        assert np.any(frame == 0)
