# redsun-mimir - agent & contributor conventions

Single source of conventions for agents (Claude, Copilot) and contributors.
Cross-link, don't duplicate.

`redsun-mimir` is a plugin bundle, not a framework. Ships devices, presenters, views
that [`redsun`](https://github.com/redsun-acquisition/redsun) framework
discovers and wires. `redsun` documents framework rules; this file records only
what is specific to the bundle.

## Repository layout

```
src/redsun_mimir/
  redsun.yaml      # PLUGIN MANIFEST - every shipped component and service
  services/        # one process per piece of hardware, served over PVAccess
                   #   mmcore_camera.py, mmcore_stage.py, uc2_controller.py
                   #   _process.py     - serving, readiness, stdin watcher
                   #   _uc2_serial.py, _uc2_actions.py - the board's wire protocol
  device/          # ophyd-async devices, clients of those services
                   #   _mocks.py     - mock hardware (no drivers needed, CI-safe)
                   #   containers.py - ReadableDeviceMap
                   #   mmcore/    - camera and stage clients
                   #   youseetoo/ - UC2 motor and laser clients (no CI coverage)
  presenter/       # acquisition, detector, light, median, motor
  view/            # Qt/napari widgets: acquisition, detector, image, light, motor
  configurations/  # runnable example containers (_full_simulation, _full_uc2)
                   #   + their .yaml session files, _base.py (MimirApp), _wiring.py
  common/          # what every layer shares: Roi, the stream names
  protocols.py     # bundle-local structural protocols
  providers.py     # provider keys
  hooks.py         # NapariApplication, FONT_SIZE
  utils/napari/    # napari callbacks, overlay, stylesheet
tests/             # flat: conftest.py + test_<subsystem>.py
pyproject.toml     # all tool config: pytest, ruff, mypy, coverage
```

Entry point:
`[project.entry-points."redsun.plugins"] redsun-mimir = "redsun.yaml"`,
which redsun plugin discovery reads.
`mimir <sim|uc2>` (`__main__.py`) launches the example containers.

## Build & validate

```bash
uv sync --group dev                      # dev env (pulls pyqt + sim + uc2 groups)
uv run pytest                            # full suite (testpaths=tests)
uv run pytest tests/test_devices.py -x    # scoped, fast
uv run ruff check --fix . && uv run ruff format .
uv run mypy src/ $(uv run qtpy mypy-args)
mmcore install --test-adapters           # once: DemoCamera adapters for mmcore tests
mmcore list                              # verify: the active install must be DIV-compatible
```

### Shell

`cmd.exe` has no `$(...)`. On Windows use PowerShell and write the mypy args
as `@(uv run qtpy mypy-args)`. Prefer PowerShell over `cmd.exe` for Claude
Code sessions on this repo.

### mypy

Always run mypy through qtpy shim. Pins Qt binding mypy resolves against, and
is what CI runs. Bare `mypy src/` diverges once both pyqt6 and pyside6 present.

mypy is `strict = true` with `warn_unreachable` and `files = ["src", "tests"]`,
so tests type-checked as strictly as package, same as redsun. Only
`import-untyped`, `import-not-found`, `no-untyped-call` disabled. Do not widen
list to silence real error.

### pytest

`asyncio_mode = "auto"` set. Do not decorate async tests with
`@pytest.mark.asyncio`.

Skip markers are public names (`needs_opengl`, `needs_mm_adapters`). Each
marker imported by modules using it, so underscore only makes import look like
mistake.

### Qt and napari

Qt tests need display. On Linux without one, set `QT_QPA_PLATFORM=offscreen`
yourself; nothing sets it for you. Use session-scoped `qapp` fixture from
`conftest.py`. Never build `QApplication` yourself.

`offscreen` has no OpenGL context, napari `QtViewer` needs real one. Anything
constructing `ImageView` carries `needs_opengl` from `conftest.py`, skipped
unless `MIMIR_TEST_OPENGL` set. CI provides context with
`pyvista/setup-headless-display-action` and sets that variable, so no workflow
pins `QT_QPA_PLATFORM` for test run.

### Micro-Manager adapters

Adapters downloaded, not pip-installed. Device interface version must match
installed `pymmcore` - `mmcore list` marks mismatched install `(incompatible)`.
Install only test adapters (`--test-adapters`): every mmcore device here is
`adapter="DemoCamera"`, and CI installs that via
`pymmcore-plus/setup-mm-test-adapters`. Mark test loading real device with
`needs_mm_adapters` from `conftest.py`, so machine without adapters skips
instead of failing inside `loadDevice`.

## Architecture invariants

Every user-intended device, presenter, view class must appear in
`src/redsun_mimir/redsun.yaml` under right section, as `module.path:ClassName`.
Class missing from manifest invisible to redsun however correct. Manifest entry
that does not resolve breaks plugin discovery for whole bundle. Adding
component -> same-commit manifest entry.

Devices are `ophyd-async` devices. Hardware access async; no threads for I/O.
`DeviceMap` comes from `ophyd_async.core`.

Presenter constructors must lead with exactly `(name, devices)`, view
constructors with `(name)`. Framework validates positional shape at discovery
and protocol via `isinstance` on built instance. Do not inherit
`PPresenter`/`PView`: property descriptors shadow instance attributes at
runtime. Data members exposed to framework are read-only properties.

Signals named `sig_snake_case`, never `sigCamelCase`. Signals sharing name
across components disambiguated by owner:
`find_signals(container, names, owner=...)`.

Bundle writes acquisition bytes in service owning hardware, not in session:
camera service writes capture window with `acquire-zarr`, device reports it
with `StreamResource`/`StreamDatum`. Derived products go through
`redsun.writers.Writer`, which `MedianPresenter` uses to add the scan's stack as
`<detector>_scan` to store the capture names. Median stays in memory.

Service = process session starts and stops. Declared in `redsun.yaml` under
`services:`, session file names it, device points at it with `service=`; prefix
reaches process through environment. `services/_process.py` holds what every
service does around its `fastcs` controller.

Signal a connector fills at connect does not exist when device constructed. So
container of such children is `ReadableDeviceMap` (`device/containers.py`)
rather than `DeviceMap` registered as readable, and `MMCamera` merges its
properties into `read_configuration` itself.

Plan collecting `StandardDetector` must pre-declare stream with
`bps.declare_stream(det, name=..., collect=True)` before `bps.collect`.

Device build failures logged and skipped; presenter and view build failures
abort app. Device that cannot reach hardware must fail at build, not
half-initialise.

`youseetoo/` talks to real serial hardware, cannot be covered in CI. Service
exercised against `loop://` port and fake board answering protocol; board
itself tested by hand (see README warning).

## Code conventions

- Python >=3.11, `from __future__ import annotations` everywhere (ruff
  `FA102`).
- Ruff lint has `D` (numpy docstring convention), `I`, `TC`, `PERF` enabled:
  runtime-unneeded imports go under `if TYPE_CHECKING:`. Public symbols need
  docstrings; `D100`/`D103`/`D104`/`D107` ignored.
- Private modules `_underscored`; each package `__init__.py` re-exports public
  surface with explicit `__all__`. New public symbols go in both - and, if
  user-facing, in `redsun.yaml`.
- asyncio only. Hardware goes through `ophyd-async`; Qt work stays on Qt
  thread, crosses over via psygnal signals.
- Public API change -> docstring + `CHANGELOG.md` entry.

## Testing conventions

- Tests flat under `tests/`, one file per subsystem (`test_devices.py`,
  `test_presenters.py`, `test_views.py`, `test_services.py`, `test_camera.py`).
  Extend existing file, don't add parallel one.
- Test needing hardware drives it through service, with fixtures in
  `conftest.py` (`camera_service`, `stage_service`, `uc2_service`, and devices
  built on them). Controller can also be driven in-process with fake core or
  fake serial port, needing no adapters and no PVA.
- Waiting on worker thread is event, not deadline: poll loops with timeout make
  test fail under load and hide what broke.
- Mock hardware only. Real drivers never appear in suite: use
  `device/_mocks.py`, ophyd-async `mock=True` connect, Micro-Manager `demo`
  device adapters via `pymmcore-plus`. Anything requiring serial port or real
  camera out of scope for CI.
- Example containers in `configurations/` are shipped artifacts, so smoke-test
  with mock devices (build container, assert components come up) rather than
  leave to manual runs.
- Prefer public interface. For multi-step lifecycle write one happy-path test
  driving whole sequence, asserting observable end state, then small focused
  tests for unhappy paths.
- Parametrize normal and edge cases together in one `@pytest.mark.parametrize`.
- All imports at top of module, tests too. No function-level imports;
  runtime-unneeded imports go under `if TYPE_CHECKING:`.
- Shared fixtures belong in `conftest.py`, not duplicated per file.

## Response style (agents)

- Terse. No preamble, no restatement of request, no summary of what you just
  did.
- Show diffs, not whole files. Don't explain code unless asked.
- Don't narrate intent ("I'll now...") - just make change.
- State assumptions in one line; ask only when genuinely blocked.

## Docstrings and comments

- Docstrings concise, minimal: only behaviour of thing defined, scoped to that
  definition. Write for reader with nothing but docstring in front of them - no
  references to design documents, decision records, anything outside immediate
  context.
- No section-divider or banner comments, no comment blocks describing code that
  follows. Comment earns place only by explaining why specific statement is the
  way it is.
- Everything committed here scoped to this repository, assumed public: no local
  filesystem paths, no references to another project's internals.

## Updating this guide

Say "Update CLAUDE.md with..." to persist convention here. Durable, shareable
rules belong in this file, not per-session memory.
