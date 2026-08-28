# redsun-mimir - agent & contributor conventions

Single source of conventions for agents (Claude, Copilot) and contributors -
cross-link, don't duplicate.

`redsun-mimir` is a **plugin bundle**, not a framework: it ships devices,
presenters and views that the [`redsun`](https://github.com/redsun-acquisition/redsun)
framework discovers and wires. Rules that belong to the framework itself are
documented by `redsun`; this file records only what is specific to the bundle.

## Repository layout

```
src/redsun_mimir/
  redsun.yaml      # PLUGIN MANIFEST - every shipped component must be listed here
  device/          # ophyd-async devices
                   #   _mocks.py  - mock hardware (no drivers needed, CI-safe)
                   #   _logics.py - shared device logic + DEFAULT_TIMEOUT
                   #   signals.py, utils.py, median.py
                   #   mmcore/    - pymmcore-plus camera + stage
                   #   youseetoo/ - UC2 serial motor/laser (no CI coverage, see README)
  presenter/       # acquisition, detector, light, median, motor, storage
  view/            # Qt/napari widgets: acquisition, detector, image, light, motor, storage
  configurations/  # runnable example containers (_full_simulation, _full_uc2,
                   #   _acquisition, _light, _motor) + their .yaml session files
  storage.py       # storage backend(s) built on redsun's StorageIO/OpenStore split
  protocols.py     # bundle-local structural protocols
  utils/napari/    # napari callbacks + overlay helpers
tests/             # flat: conftest.py + test_<subsystem>.py
pyproject.toml     # all tool config: pytest, ruff, mypy, coverage
```

Entry point: `[project.entry-points."redsun.plugins"] redsun-mimir = "redsun.yaml"`,
which redsun's plugin discovery reads. `mimir <sim|uc2|motor|light|acquisition>`
(`__main__.py`) launches the example containers.

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

- **Windows:** `$(...)` does not exist in `cmd.exe`. Use PowerShell with
  `@(uv run qtpy mypy-args)`. Prefer PowerShell over `cmd.exe` for Claude Code
  sessions on this repo.
- **Always use the qtpy shim form of mypy** - it pins the Qt binding mypy
  resolves against, and it is what CI runs. A bare `mypy src/` diverges once
  both pyqt6 and pyside6 are present.
- mypy is `strict = true` with `warn_unreachable`, and `files = ["src", "tests"]`,
  so **tests are strictly type-checked too**, same as redsun. Only
  `import-untyped`, `import-not-found` and `no-untyped-call` are disabled;
  do not widen that list to silence a real error.
- pytest is `asyncio_mode = "auto"` - **do not decorate async tests** with
  `@pytest.mark.asyncio`.
- Qt tests need a display; on Linux without one set `QT_QPA_PLATFORM=offscreen`
  yourself - nothing sets it for you. Use the session-scoped `qapp` fixture from
  `conftest.py`, never build a `QApplication` yourself.
- **`offscreen` has no OpenGL context**, and napari's `QtViewer` needs a real
  one, so anything constructing an `ImageView` carries `needs_opengl` from
  `conftest.py` and is skipped unless `MIMIR_TEST_OPENGL` is set. CI provides
  the context with `pyvista/setup-headless-display-action` and sets that
  variable, which is why no workflow pins `QT_QPA_PLATFORM` for the test run.
- **Micro-Manager adapters are downloaded, not pip-installed**, and their device
  interface version must match the installed `pymmcore` - `mmcore list` marks a
  mismatched install `(incompatible)`. Install only the test adapters
  (`--test-adapters`): every mmcore device here is `adapter="DemoCamera"`, and
  that is what CI installs via `pymmcore-plus/setup-mm-test-adapters`. Mark a
  test that loads a real device with `needs_mm_adapters` from `conftest.py`, so
  a machine without them skips instead of failing inside `loadDevice`.
- Skip markers in tests are **public names** (`needs_opengl`,
  `needs_mm_adapters`) - a marker is imported by the modules that use it, so an
  underscore only makes that import look like a mistake.

## Architecture invariants

- **The manifest is the contract.** Every device, presenter and view class
  intended for users must appear in `src/redsun_mimir/redsun.yaml` under the
  right section, as `module.path:ClassName`. A class that is not in the
  manifest is invisible to redsun no matter how correct it is; a manifest entry
  that does not resolve breaks plugin discovery for the whole bundle. Adding a
  component -> same-commit manifest entry.
- **Devices are `ophyd-async` devices.** Hardware access is async; no threads
  for I/O. `DeviceMap` comes from `ophyd_async.core`.
- **Presenter/view contract.** Constructors must lead with exactly
  `(name, devices)` for presenters and `(name)` for views - the framework
  validates the positional shape at discovery and the protocol via `isinstance`
  on the built instance. Do **not** inherit `PPresenter`/`PView`: property
  descriptors shadow instance attributes at runtime. Data members exposed to
  the framework are read-only properties.
- **Signals are `sig_snake_case`**, never `sigCamelCase`. Signals with the same
  name on different components are disambiguated by owner:
  `find_signals(container, names, owner=...)`.
- **Storage builds on the framework's split**: `StorageIO` is backend mechanics
  (`open`/`uri`/`resource_info`), `OpenStore` is the lifecycle-bound handle
  (`write`/`release`/`close`), `BaseStorage` implements `SinkFactory` over
  both. Producers only ever hold a `FrameSink`. Do not reimplement queueing,
  draining or frame counting here.
- **Shared-storage detectors must not eagerly open** the backend at prepare: a
  sibling's `register` races the open and raises `StoreStateError`. Rely on the
  drain's lazy open. Eager open is only legal when a detector exclusively owns
  its storage group.
- **Plans collecting a `StandardDetector`** must pre-declare the stream:
  `bps.declare_stream(det, name=..., collect=True)` before `bps.collect`.
- Device build failures are logged and skipped; presenter/view build failures
  abort the app. A device that cannot reach hardware must fail at build, not
  half-initialise.
- `youseetoo/` talks to real serial hardware and **cannot be covered in CI** -
  keep it behind mocks in tests and test it manually (see README warning).

## Code conventions

- Python ≥3.11, `from __future__ import annotations` everywhere (ruff `FA102`).
- Ruff lint has `D` (numpy docstring convention), `I`, `TC` and `PERF` enabled:
  runtime-unneeded imports go under `if TYPE_CHECKING:`. Public symbols need
  docstrings; `D100`/`D103`/`D104`/`D107` are ignored.
- Private modules are `_underscored`; each package `__init__.py` re-exports the
  public surface with an explicit `__all__`. New public symbols go in both -
  and, if user-facing, in `redsun.yaml`.
- asyncio only. Hardware goes through `ophyd-async`; Qt work stays on the Qt
  thread and crosses over via psygnal signals.
- Public API change -> docstring + `CHANGELOG.md` entry.

## Testing conventions

- Tests are flat under `tests/`, one file per subsystem
  (`test_devices.py`, `test_presenters.py`, `test_views.py`, `test_storage.py`,
  `test_camera.py`). Extend the existing file rather than adding a parallel one.
- **Mock hardware only.** Real drivers never appear in the suite: use
  `device/_mocks.py`, ophyd-async's `mock=True` connect, and the Micro-Manager
  `demo` device adapters via `pymmcore-plus`. Anything requiring a serial port
  or a real camera is out of scope for CI.
- The example containers in `configurations/` are shipped artifacts - they must
  be smoke-tested (build the container, assert the components come up) with
  mock devices, not left to manual runs.
- Prefer the public interface. For a multi-step lifecycle write one happy-path
  test driving the whole sequence and asserting the observable end state, then
  small focused tests for unhappy paths.
- Parametrize normal and edge cases together in one `@pytest.mark.parametrize`.
- **All imports live at the top of the module** - in tests too. No
  function-level imports; runtime-unneeded imports go under `if TYPE_CHECKING:`.
- Shared fixtures belong in `conftest.py`, not duplicated per file.

## Response style (agents)

- Terse. No preamble, no restatement of the request, no summary of what you
  just did.
- Show diffs, not whole files. Don't explain code unless asked.
- Don't narrate intent ("I'll now…") - just make the change.
- State assumptions in one line; ask only when genuinely blocked.

## Docstrings and comments

- Docstrings are concise and minimal: only the behaviour of the thing being
  defined, scoped to that definition. Write for a reader who has nothing but
  the docstring in front of them - no references to design documents, decision
  records or anything outside the immediate context.
- No section-divider or banner comments, and no comment blocks describing the
  code that follows. A comment earns its place only by explaining why a
  specific statement is the way it is.
- Everything committed here is scoped to this repository and assumed public:
  no local filesystem paths, and no references to another project's internals.

## Updating this guide

Say **"Update CLAUDE.md with…"** to persist a convention here. Durable,
shareable rules belong in this file - not in per-session memory.
