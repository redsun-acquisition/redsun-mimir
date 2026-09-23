# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Dates are specified in the format `DD-MM-YYYY`.

## [Unreleased]

### Added

- `--no-reset` (`redsun_mimir.services.uc2_controller`) - opens the serial
  port without restarting the board, for a port with no board behind it.
- `DeviceLocks` (`redsun_mimir.common`) - names the devices a plan holds, with
  `hold(*devices)` as a context manager and `sig_locks_changed` emitting the
  set when it changes.
- `AcquisitionPresenter.locks` and `AcquisitionPresenter.sig_locks_changed` -
  a plan holds the devices in its arguments until it ends; a paused plan keeps
  them.
- `MotorView.set_locked`, `LightView.set_locked`, `DetectorView.set_locked` -
  disable the controls of the named devices; readouts keep updating.

  ```python
  def scan(self, stage: Stage, camera: Camera) -> MsgGenerator[None]:
      with self.locks.hold(self.laser):
          yield from bps.mv(self.laser.power, 5)
  ```

### Changed

- `redsun` 0.13.0 is the minimum version, in the dependencies and the `pyqt`
  and `pyside` extras.
- The example sessions are named `mimir-sim` and `mimir-uc2`, each in its own
  configuration file.
- `AcquisitionPresenter.square_scan` takes a frame before every move, starting
  where the motor stands; the last move closes the square.
- `redsun_mimir.services.mmcore_camera` reads no camera property and no
  `PixelType` while the camera sequences. A property written meanwhile is read
  back while the sequence is paused.
- `ImageView` locks each detector layer against deletion from the layer list
  (napari's `LayerLock.DELETION`). A user who unlocks and deletes one gets it
  back with the next frame.

### Changed (breaking)

- The `positions` metadata `MedianPresenter` writes beside a scan stack is one
  record per frame, in stack order, with its `frame_id` and the `axes` it was
  taken at.

### Fixed

- `ImageView.update_layers` rebuilds a detector layer the user deleted as a
  sensor-sized, writable layer with its selection box.

## [0.4.1] - 07-09-2026

### Changed

- `MotorView` (`redsun_mimir.view.motor`) - revamped UI (napari settings were causing weird visualization)
- bump `redsun` to 0.12.2, which fixes a bug in the `psygnal` emission queue
- bump `napari` to 0.9.1

## [0.4.0] - 03-09-2026

### Added

- `pixel_dtype` is writable, on the service as an enum of the numpy dtype
  names the camera reads out in, `uint8`, `uint16` or `uint32`, and as
  `SignalRW[str]` on `MMCamera` and `DetectorProtocol`. The names map to
  Micro-Manager's `PixelType` through `PIXEL_TYPES` in
  `redsun_mimir.services.mmcore_camera`, limited to the values the camera
  allows, and reach a client as the signal's `choices`, so the settings tree
  offers them in a combo box. A change while a capture window writes is
  refused, since the store's dtype was fixed when the window opened.
  `PixelType` is never published as a property.

- The three services (`redsun_mimir.services`) log serialized `loguru`
  records to their standard output; the session rebuilds each under
  `redsun.service.<name>.<logger>` with its level, time and logger name.

- A selection box on each detector layer of `ImageView`, shown on request and
  dragged by its handles to choose a region of the sensor. Dragging announces
  the box as a `Roi` on `ImageView.sig_roi_drawn` and changes nothing on the
  camera; `ImageView.on_new_configuration`, wired to the detector presenter,
  moves the box to the region the camera reads once a ROI is applied.
- A ROI panel under each detector's settings in `DetectorView`: the region the
  camera reads and Select ROI, which opens an editor of four spin boxes, `x`
  and `y` over `width` and `height`, with Full and OK. Select ROI shows the box
  on the image through `DetectorView.sig_roi_selection`, wired to
  `ImageView.set_roi_selection`; the box is hidden and inert otherwise. The
  box and the spin boxes show one region: a drag arrives on `on_roi_drawn`,
  wired from `ImageView.sig_roi_drawn`, and an edit leaves on
  `DetectorView.sig_roi_edited`, wired to `ImageView.set_roi_box`. OK sends the
  region as a `roi` property change through `sig_property_changed` and closes
  the editor; nothing reaches the camera before that.
- A `roi` change asked for while a plan runs is applied between two of its
  messages. `AcquisitionPresenter.register_providers` provides the engine's
  `Deferrals` under `redsun.engine.DEFERRALS` and
  `DetectorPresenter.inject_dependencies` takes it; a session without an
  acquisition presenter applies the change at once.
- `sensor_size` on the camera service (`redsun_mimir.services.mmcore_camera`)
  and on `MMCamera` (`redsun_mimir.device.mmcore`): the whole sensor as
  `(width, height)`, read once while nothing crops the camera, part of the
  camera's configuration and a member of `DetectorProtocol`
  (`redsun_mimir.protocols`).
- `FONT_SIZE` (`redsun_mimir.hooks`) - the point size every widget of a
  session is drawn at, 9. `NapariApplication` applies napari's stylesheet at
  that size; `stylesheet(font_size=...)` (`redsun_mimir.utils.napari`) takes
  the size, napari's own setting when left out.
- `redsun`'s log view in both sessions, declared as `logs` on `MimirApp`.

- A directory control in `AcquisitionView`: a read-only field showing where a
  run writes and a Browse button. The choice travels as `sig_base_dir_request`
  to `AcquisitionPresenter.set_base_dir` and is announced on
  `sig_base_dir_changed` to the session's path provider and back to the view.
  A request made while a plan runs is logged and dropped.

- `NapariApplication` (`redsun_mimir.hooks`) - a container hook serving
  `create_application` and `configure_application`: it runs the session on
  napari's application and applies napari's stylesheet to it.

  ```yaml
  hooks:
    create_application: &napari
      provider: "redsun_mimir.hooks:NapariApplication"
    configure_application: *napari
  ```

- `stylesheet` (`redsun_mimir.utils.napari`) - napari's QSS for the theme and
  font size in its settings.

- `build_uc2_container` (`redsun_mimir.configurations`) - the UC2 container,
  unbuilt, matching `build_simulation_container`.

- `redsun_mimir.services.mmcore_camera` - a Micro-Manager camera served over
  PVAccess. It owns a `CMMCorePlus`, reads frames through
  `startContinuousSequenceAcquisition`, writes a capture window to a Zarr
  store with `acquire-zarr`, and publishes every property the camera lets a
  client write under `properties`. `State` reads `idle`, `acquiring` or
  `faulted`, and `LastError` carries the exception that stopped it.

  ```yaml
  services:
    transport: pv-access
    camera1_ioc:
      plugin_name: redsun-mimir
      plugin_id: mmcore-camera
      prefix: "MIMIR-CAM1:"
      args: ["--adapter", "DemoCamera", "--device", "DCam"]
  ```

- `redsun_mimir.services.mmcore_stage` - a Micro-Manager stage served over
  PVAccess, one process per stage, its axes given as `--axes x,y`. Moves are
  serialised.

- `redsun_mimir.services.uc2_controller` - a YouSeeToo board served over
  PVAccess, owning the serial port, with a sub-controller per axis and per
  laser. `--port` takes anything `pyserial` opens by url, `COM4` included.

- `MMStage` (`redsun_mimir.device.mmcore`) - a stage reached through its
  service, its axes taken from the served PVI tree.

- `ReadableDeviceMap` (`redsun_mimir.device`) - a `DeviceMap` that answers
  `read` and `describe` from the entries it holds, including entries a
  connector adds at connect.

- `common_configuration.yaml` (`redsun_mimir.configurations`) - the identity,
  presenters and views both sessions share. `full_configuration.yaml` and
  `uc2_full_configuration.yaml` carry a `devices` section only and are laid
  over it.

### Changed

- `redsun_mimir.services.mmcore_camera` publishes the camera's own properties
  only when named with `--properties`, comma-separated; none without it.
  `MMCameraController` and `build_controller` take the same list as
  `properties`, every writable one when left out.

- `AcquisitionPresenter.live_median_scan` and `live_stream` run each capture
  as a run of its own, nested in the plan's, through
  `AcquisitionPresenter.capture`. The capture's start document carries
  `purpose: capture`, `parent`, the plan's run, and `median_scan`, the uid of
  the last scan or `null` (always `null` from `live_stream`); it declares its
  stream, so its descriptor and `stream_resource` name the store it writes.
  `square_scan` returns the scan run's uid and its start document carries
  `parent` too. The stack `MedianPresenter` writes carries `scan_run` beside
  `derived_from` and `stream`.
- A camera's `roi` is text, `"x,y,width,height"`, on the service and on
  `MMCamera`, and `DetectorProtocol.roi` is a `SignalRW[str]`; `Roi` in
  `redsun_mimir.common` reads and writes the form.

- A detector's layer in `ImageView` is the size of the sensor, from the
  camera's `sensor_size`, and stays that size: a frame taken with a ROI is
  drawn into the rectangle the ROI names. `DetectorPresenter.sig_new_data`
  carries `<detector>-roi` beside `<detector>-buffer` for that.

- `MMCamera` (`redsun_mimir.device.mmcore`) takes the prefix of its service
  and builds its signals from PVI. It reports what the service wrote through
  `StreamResource`/`StreamDatum`, and `describe_configuration` carries the
  camera's own properties beside `exposure` and `roi`.

- `UC2MotorDevice` and `UC2LaserDevice` (`redsun_mimir.device.youseetoo`) take
  the prefix of the service that owns the board and build their signals from
  PVI. Neither opens a serial port.

- `MotorProtocol.axis` is a read-only `Mapping[str, StandardMovable[float]]`.

- `DetectorPresenter.set` accepts any setting the detector publishes in
  `describe_configuration`, keyed as the view names it, not only `exposure`
  and `roi`.

- `MedianPresenter` writes the scan's stack of frames with a
  `redsun.writers.Writer` into the store the acquisition's `StreamResource`
  names, under `<detector>_scan`, with `derived_from`, `stream`, `scan_run`,
  `positions` and the run's `redsun` provenance on the key. `positions`
  holds every reading of the scan's events beside the frames, one list per
  key aligned with the stack: the motor's axes, which `square_scan` reads
  into each frame's event. The median is computed from that
  stack at the scan's stop, kept in memory for the live correction and
  dropped when the plan ends. The presenter forwards every document to the
  writer, `stop` after its own dispatch, and `shutdown` closes a store a run
  left open.

- The detector view sizes an intensity slider from a signal's display limits
  when it carries no control ones.

- The minimum `redsun` version is 0.13.0rc4, and the bundle installs
  `fastcs[epicspva]` and `ophyd-async[pva]`.


- The example sessions ask for their log level with
  `MimirSimulator(log_level=logging.DEBUG)`.

- Both example sessions are built on one container. `MimirApp` declares the
  hooks, the presenters, the views and `wire`; `MimirSimulator` and
  `MimirMicroscope` add their devices and the file that configures them.

- `LightProtocol.trigger` returns `AsyncStatus[None]`. `AsyncStatus` is
  generic in the value it produces from `ophyd-async` 0.21.2 onwards.

### Removed

- `UC2Serial` (`redsun_mimir.device.youseetoo`). A session declares the
  `youseetoo-controller` service and names it from each device's `service:`.

- `MMDemoXYStage` and `MMDemoZStage` (`redsun_mimir.device.mmcore`), replaced
  by `MMStage`. The adapter, the device and the axis names go in the service
  declaration.

- `redsun_mimir.storage`, and the `storage_ctrl` and `storage_widget`
  declarations from the example sessions. A session takes an optional
  `storage:` section instead, and the plan name reaches the session's path
  provider.

- `ImageView` no longer applies napari's stylesheet to itself and its
  embedded `QtViewer`, nor sets the theme on its viewer model; the session's
  `configure_application` hook styles it. With `NapariApplication` installed
  it renders as before.

- The `light`, `motor` and `acquisition` example containers, their
  configuration files and their `mimir` CLI subcommands. `redsun_mimir.configurations`
  exposes `build_simulation_container`, `run_simulation_container` and
  `run_uc2_container`; the CLI accepts `sim` and `uc2`.

### Fixed

- `MMCameraController.reconnect` after a fault starts grabbing again even
  when the failed thread's task has not been reaped by the event loop yet;
  before, a reconnect asked for in that window was dropped and the camera
  stayed idle.

- `DetectorPresenter` ignores the empty string a ROI subscription delivers
  before the service has published a value, instead of raising
  `ValueError` inside the subscription callback.

- `ImageView` enables the viewer grid through `canvas.grid`, the attribute
  `napari` 0.9 keeps, instead of the deprecated `viewer.grid`.

- `ImageView` blanks a detector's layer when a ROI is applied, so the
  sensor outside the new region shows black rather than the last frames, and
  drops a frame whose shape is not its ROI's, the one a monitor reports
  first at the next plan, which painted the old region back.

- The camera service publishes a frame with the dtype the camera now gives,
  retyping `buffer` when `pixel_dtype` changed it; a frame of a new dtype
  was cast to the first frame's. `ImageView` retypes a layer to the frame it
  receives.

- `DetectorPresenter` knows its writable settings from construction. They
  were collected on the first ROI update, so a `set` or a settings tree built
  before it found none.
- `DetectorPresenter.devices_description` marks a setting it cannot write,
  `pixel_dtype` and `sensor_size`, with `:readonly` on its source, so the
  settings tree shows it as a label. An edit there was refused with
  `Unknown property`.
- A Micro-Manager stage move whose readback settles one reporting step from
  its target completes, and one that never settles raises after
  `MOVE_TIMEOUT` (10 s) instead of waiting forever. The service reports
  positions to two decimals, so a move starting off that grid can read
  0.01 um away; `POSITION_TOLERANCE` is 0.02. A square scan of ten steps per
  side stalled on its ninth step.
- A second capture window in one session completes: the camera service starts
  `Captured` over when handed a store, and `MMCamera` waits for that before
  describing the window. The count carried over from the last window, so the
  second timed out waiting for twice its frames.
- An unbounded capture window (`write_forever`) reports every frame it wrote:
  `MMCamera` closes the window as the plan completes, and the camera service
  publishes the final count as it closes. Closed at unstage, after the
  documents were emitted, the window left its last frames on disk unaccounted
  for.
- `AcquisitionPresenter` emits `sig_plan_done` for a togglable plan too, so
  the session's path provider forgets the plan once a stream is stopped and a
  later directory change is accepted. `stop_plan` does nothing while the engine
  is idle, rather than raising into the view's Stop button.
- `AcquisitionView` holds the plan selector on the plan that runs until it is
  done, and acts on that plan when it ends, whichever is selected meanwhile.
  `AcquisitionPresenter.launch_plan` refuses a launch while a plan runs, rather
  than clearing the running plan's action latches.
- `AcquisitionPresenter.launch_plan` resets the action latches of the last
  launch. A stream stopped while its window wrote left its latch set, and the
  next launch started writing with no click.
- A camera property Micro-Manager refuses during a sequence acquisition,
  binning and pixel type among them, is written with the sequence paused around
  it, as a `roi` is. The pause is ordered against the grabbing thread, which
  exposes only while no sequence runs.
- `DetectorPresenter.set` logs a write the device refuses, rather than raising
  out of the slot and leaving the view's pending edit unanswered.
- `MedianPresenter` writes the scan's stack into the store the run around
  the scan names, whether that store is named before the scan or after it. A
  scan before the stream, the order the plan documents, wrote nothing, and a
  later plan wrote into the previous plan's store.
- `UC2LaserDevice.trigger` keeps an intensity set while the laser read off.
  Turning the laser on restored the intensity saved at the last off, dimming
  it past a slider moved meanwhile.
- `MMCamera` reads the service's `state` and `last_error`, and a `trigger` or a
  window's completion on a faulted camera raises with the camera's own error
  rather than timing out. The service forgets a fault when grabbing restarts,
  so `Acquire` toggled after one no longer reads `faulted` for good.
- `ImageView.closeEvent` unregisters its viewer providers through
  `InjectionContext.cleanup` rather than calling the context, which raised
  `TypeError` and left the providers registered.

## [0.3.1]

Motor axes are ophyd-async movables, and the position they report is read from
the device instead of echoed back from the last request.

### Changed (breaking)

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

## [0.3.0] - 01-08-2026

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

[0.4.1]: https://github.com/redsun-acquisition/redsun-mimir/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/redsun-acquisition/redsun-mimir/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/redsun-acquisition/redsun-mimir/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/redsun-acquisition/redsun-mimir/compare/v0.2.0...v0.3.0
[0.1.0]: https://github.com/redsun-acquisition/redsun-mimir/compare/v0.1.0
