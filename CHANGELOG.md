# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Dates are specified in the format `DD-MM-YYYY`.

## [Unreleased]

Migration to `redsun` 0.11.0, covering two reworks of the framework: the 0.10.0
device and storage redesign, and the 0.11.0 move to application-declared wiring
and typed providers. See redsun's own changelog for both.

The headline for anyone upgrading: **components no longer connect themselves**,
and three presenter entry points became coroutines that no longer block the
caller.

### Changed (breaking)

- Requires `redsun>=0.11.0`. `culsans` is no longer declared here; it arrives
  with redsun.
- **Components no longer connect themselves.** Every connection this bundle
  used to make from `inject_dependencies` via `find_signals` is now declared by
  the application: the shipped containers do it in `wire()`, a YAML session in
  a `wiring:` section. **A session that does neither connects nothing** - it
  builds and sits inert. The README carries the block to copy.

  Four presenters lost `inject_dependencies` entirely; every view keeps a
  shorter one that only reads DI values.
- **Six methods became public, connectable slots** (`@slot`):
  `ImageView.update_layers`, `MotorView.update_setpoint`,
  `DetectorView.on_new_configuration`, `AcquisitionView.on_plan_done`,
  `AcquisitionView.on_action_done`, `MedianPresenter.clear_medians`. The
  private names are gone.
- **Device calls no longer block the caller.** Three entry points were sync
  methods whose whole body was `run_coro(...)`, which blocks the calling thread
  (in practice the Qt main thread) until the device answers. They are
  coroutines now, connected directly:

  | Was | Is |
  |---|---|
  | `DetectorPresenter.configure(detector, property, value)` | `await DetectorPresenter.set(...)` |
  | `MotorPresenter.move(...)` (sync) wrapping `move_async` | `await MotorPresenter.move(...)` |
  | two lambdas over `LightPresenter.trigger` / `set` | the coroutines, connected directly |

  Calling any of them directly now requires `await`. An exception inside one is
  logged on the `redsun` logger instead of propagating to the emitter.
  `DetectorPresenter._set` is gone; `set` does the whole job.

  An application that is not a `QtAppContainer` must call
  `redsun.aio.set_async_backend()` before `build()`, or psygnal rejects these
  slots at connect time.
- **`MotorView.sig_motor_move` carries a displacement, not a target.** The
  signature is unchanged (`Signal(str, str, float)`), so nothing fails to
  connect, but the third argument was an absolute position and is now a
  relative step. **Anything connected to this signal must be updated, and
  nothing will tell you if it is not.**
- **Position labels are driven by the axes, not by the presenter.**
  `MotorPresenter.sig_new_position` is gone and `MotorView.update_setpoint`
  takes the reading dictionary a signal subscription delivers:

  ```python
  view.update_setpoint("stage", "x", 3.25)  # was
  view.update_setpoint({"stage-axis-x": reading})  # is
  ```

  The view subscribes to every axis readback published under the new
  `MOTOR_READBACKS` provider key, so a label now follows the stage itself
  rather than the last request the widget sent: a move made by a plan, or one
  a hardware limit clamped, shows up. There is no rule to write for it in a
  `wiring:` section, and the corresponding line in `wire_motor` is gone.
- **`MedianPresenter.sig_new_median` and `sig_new_filtered_data` are now
  `frames.median` and `frames.filtered`** on a strict `SignalGroup`:

  ```python
  presenter.sig_new_median.connect(fn)  # was
  presenter.frames.median.connect(fn)  # is
  ```

  In a `wiring:` section the port names are `median` and `filtered`.
- **DI providers are typed keys**, collected in `redsun_mimir.providers`:

  ```python
  specs = container.detector_layer_specs()  # was
  specs = container.require(DETECTOR_LAYER_SPECS)  # is
  ```
- `FileStorageView` moved into redsun and was renamed `StorageView`. A
  configuration naming it must change plugin:

  ```diff
    storage_widget:
  -    plugin_name: redsun-mimir
  +    plugin_name: redsun
      plugin_id: storage
  ```

  A container importing the class uses `redsun.view.qt.builtins.StorageView`.
- **Signal naming**: every signal is now `sig_snake_case` instead of
  `sigCamelCase` (ADR 0004), e.g. `sigPreLaunchNotify` ->
  `sig_pre_launch_notify`. Downstream code connecting to these signals by
  name must be updated. This also restores interoperability with redsun's
  built-in `StoragePresenter`, which looks up the snake_case names.
- **The write window is now the sink lifecycle** (ADR 0002 D10/D12): the
  `write_sig` signal and the `set_writing` plan stub are gone. Frames reach
  viewers from `prepare` onwards and reach storage between `kickoff` and
  capacity. `prepare_and_kickoff` is replaced by `prepare_and_declare`, with
  `kickoff` issued when the write window should open.
- `AcquisitionPresenter(callbacks=None)` - the default - now subscribes
  **every** document callback registered on the virtual container, instead of
  none. With live visualization and median filtering both document-driven, an
  unlisted callback is a silently blank viewer; none of the shipped session
  YAMLs set `callbacks`, so nothing was subscribed at all. Pass an explicit
  list to restrict the selection, or `[]` to subscribe none.
- **Live visualization travels as Event documents.** Plans put each
  detector's buffer signal under `bps.monitor` (stream `live_view`), and
  `DetectorPresenter` is now a `DocumentRouter` that forwards those frames.
  The previous `subscribe_reading` hook bypassed the document sequence
  entirely, so displayed frames were invisible to any callback reasoning
  about the run. `bps.monitor` is the general mechanism for slow-changing
  observables such as live views.
- **Background-median correction is `MedianPresenter`'s job.**
  `DetectorPresenter` forwards frames raw; `MedianPresenter` caches the scan
  stack, computes the median, then divides each incoming live frame by it and
  publishes the result on `frames.filtered` under a `<detector>_filtered`
  key - so raw, median and filtered are three distinct viewer layers.
- **Buffer signal updates are throttled.** `MMAcquireLogic` refreshes the
  buffer at most once per `live_period` (default 0.1 s, settable per camera)
  and hands the viewer a *copy*; storage still sees every frame. Updating on
  every grab would push the full acquisition rate through the document router
  and the Qt main thread for no visual gain.
- **Median computation moved from a device to a document callback.**
  `MedianDevice` (which computed no median - the `np.median` call lived in
  the plan) is deleted. `MedianPresenter` is now a `DocumentRouter` that
  accumulates the frames of the background scan and computes, publishes and
  writes the median when that run stops. `square_scan` emits its stack as a
  nested run, giving the presenter a run-scoped boundary.
- Cameras take an optional `storage: BaseStorage`; when omitted they build
  their own and publish it with `register_storage(<device name>, storage)`
  so siblings can resolve it via `get_storage`.

### Removed

- `DetectorPresenter.emit_new_data` - dead since live frames moved to the
  document path, and a second emit site with a different key-rewriting rule.
- `DetectorPresenter.configure`, replaced by `set`.
- `MotorPresenter.move_async`, renamed `move`; the sync `move` it wrapped is
  gone.
- `redsun_mimir.view.FileStorageView` and its `redsun.yaml` entry.
- `redsun_mimir.storage` (`SessionPathProvider`, `get_path_provider`) - a
  reimplementation of `redsun.storage.SessionPathProvider`, which is now
  used directly. The local copy froze the date at construction and so served
  a stale date after midnight.
- `redsun_mimir.presenter.storage.FileStoragePresenter` - ported into redsun
  as `redsun.presenter.builtins.StoragePresenter`; declare that instead.
- `redsun_mimir.device.median` (`MedianDevice` and its logics/signals).
- `redsun_mimir.device.utils` (dead `attrs` converters) and
  `redsun_mimir.device.youseetoo.utils` (a duplicate `BaudeRate`).
- The hand-rolled per-detector queue, drain, capacity counter, writer
  refcounting and `aiologic` arm/disarm gating - `BaseStorage`/`FrameSink`
  own all of it now. `aiologic` is no longer a dependency.
- `MedianFlyer` protocol and `ReadableFlyer.write_sig`.
- Root `test_script.py` - an obsolete duplicate of `mimir acquisition` that
  launched a GUI at import time.

### Added

- **Motor axes are `StandardMovable` devices.** Each axis in
  `MotorProtocol.axis` is now an ophyd-async movable, built on the documented
  `StandardReadable` + `StandardMovable` mixin rather than being a bare
  `SignalRW`. Setpoint and readback are separate signals, so `locate()` reports
  what was commanded and what was measured as two distinct numbers. Axes also
  gain `stop()`, `check_value()` and `WatcherUpdate` progress reporting.

  Reading keys are unchanged (`<device>-axis-<name>`), so views, providers and
  wiring are unaffected. Code reaching into `motor.axis[...]` keeps `.set()`;
  `.get_value()` becomes `.locate()`.

  - Micro-Manager axes read the stage position live. The demo stage settles on
    its own grid rather than exactly where it was sent, so a move completes
    once the readback lands within `POSITION_TOLERANCE` instead of waiting for
    exact equality.
  - YouSeeToo axes report `setpoint == readback`, because the controller
    acknowledges commands but cannot be queried. That echo already existed; it
    is now declared by the device rather than hidden behind a signal that
    looked readable.
- **Binary light sources.** `LightProtocol` gained a read-only `binary` signal,
  and `MockLightDevice` a `binary=` argument. A binary source keeps its
  `intensity` signal, so every light has the same shape, but `LightPresenter.set`
  refuses to apply a value and `LightView` offers only the on/off button. The
  simulated `led` is declared `binary: true`; it previously showed a 0-200 mW
  slider that did not reflect the device it stands for.
- `redsun_mimir.providers`, the typed keys this bundle binds on the virtual
  container, importable by a third-party component without pulling in a
  presenter.
- `redsun_mimir.configurations._wiring`, the connection helpers the shipped
  containers share. Each takes the components it connects rather than the
  container, so every port is checked against the class that declares it.
- `build_*_container()` factories next to each `run_*_container()`, returning
  the container unbuilt so it can be built and inspected without entering the
  Qt event loop. Imports stay inside the factory, so importing
  `redsun_mimir.configurations` still does not pull in napari and Qt.
- Test coverage for what had none: the plugin manifest (`test_manifest.py`
  resolves every entry and reverse-checks that no shipped presenter or view
  is missing), the example containers (`test_configurations.py`), the
  document-driven `MedianPresenter`, and `AcquisitionPresenter`.

### Fixed

- **A `QtView` slot could be connected without main-thread marshalling.**
  `AcquisitionView` had one such connection whose slot mutated Qt widgets while
  the emission originated on the run engine's worker thread. Thread affinity
  now comes from `QtView` rather than from each connection, so the class of bug
  is closed, not just the instance.
- **Two quick clicks on a motor step button produced one step.** The view
  computed an absolute target by reading its own position label, which only
  refreshes once a move completes; a second click before that read the stale
  value and asked for the same position. It sends a displacement now.
- **Two moves on one motor could overlap.** On a Micro-Manager XY stage,
  stepping `x` and then `y` in quick succession could revert the `x` move,
  because the driver writes both coordinates on every set. Moves are serialised
  per device.
- The GUI thread no longer blocks on hardware when a detector property, a motor
  position or a light source is changed from a widget.
- **The Micro-Manager stages could not be constructed at all.** `MMDemoXYStage`,
  `MMDemoZStage` and `UC2MotorDevice` bound their axis signals as attributes
  *and* placed the same objects in a `DeviceMap`; ophyd-async refuses to
  re-parent a `Device`, so `__init__` always raised `TypeError`. The signals
  now live only in the map, and readables are taken from its values - which
  also makes readings keyed `<device>-axis-<name>`, the form
  `parse_map_key(key, "axis")` (used by `MotorView`) expects.
- `MotorView.setup_ui` indexed `descriptor["units"]`, which is optional in the
  bluesky spec, so any motor without units crashed the UI build.
- **The plugin manifest was broken**: five of its six device entries named
  classes that do not exist (`MimirSerialDevice`, `MimirMotorDevice`,
  `MimirLaserDevice`, `MMCoreCameraDevice`, `MMCoreStageDevice`), and seven
  real device classes were missing from it. `redsun.yaml` now lists every
  shipped component under its real name, and `tests/test_manifest.py` keeps
  it honest.
- `DetectorView` connected `tree_view.sigPropertyChanged`; redsun renamed it
  to `sig_property_changed`, so building a settings tab raised
  `AttributeError`.
- `DetectorView` listened for a `sigConfigurationConfirmed` signal that
  nothing emitted, so confirmed edits were never cleared from the tree
  view's pending set. It now listens to `sig_new_configuration`.
- `MotorPresenter` looked up a `sigConfigChanged` that nothing emits, and
  `MotorView` looked up `sigNewConfiguration` without an owner, which could
  match `DetectorPresenter`'s identically-named signal.
- `DeviceMap` is imported from `ophyd_async.core` (redsun removed its own).
- CI ran neither the test suite nor coverage (both were `if: false`); the
  python matrix included 3.10 despite `requires-python >=3.11`.
- Nothing skipped the Micro-Manager tests when no device adapters were
  installed: a fresh clone failed inside `loadDevice` rather than skipping.
  `tests/conftest.py` gained `needs_mm_adapters`, and CI verifies the adapters
  actually arrived instead of trusting the install step.

## [0.1.0]

- Initial release.

[0.1.0]: https://github.com/redsun-acquisition/redsun-mimir/compare/v0.1.0
