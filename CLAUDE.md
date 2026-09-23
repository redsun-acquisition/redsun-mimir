# redsun-mimir - agent & contributor conventions

Single source of conventions for agents (Claude, Copilot) and contributors.
Cross-link, don't duplicate.

`redsun-mimir` is a plugin bundle, not a framework. It ships the devices,
presenters and views that the [`redsun`](https://github.com/redsun-acquisition/redsun)
framework discovers and wires. `redsun` documents the framework's rules; this
file records only what is specific to the bundle.

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
scripts/mypy_qt.py # mypy with the qtpy flags for the binding QT_API names
pyproject.toml     # all tool config: pytest, ruff, mypy, coverage, tox
```

The entry point
`[project.entry-points."redsun.plugins"] redsun-mimir = "redsun.yaml"` is what
`redsun`'s plugin discovery reads. `mimir <sim|uc2>` (`__main__.py`) launches
the example containers.

## Build & validate

`tox` is the entry point, configured under `[tool.tox]` in `pyproject.toml`.
Every environment installs from `uv.lock` through `tox-uv-bare`, so a local run
uses the versions CI resolves rather than whatever the project `.venv`
accumulated:

```bash
uv sync --group dev                      # dev env (pulls pyqt + sim + uc2 groups)
uv run prek install                      # once: run the prek.toml hooks on every commit
uv run tox                               # lint, both mypy envs, tests
uv run tox -e tests -- tests/test_devices.py -x   # posargs reach pytest
uv run tox -e mypy-pyqt,mypy-pyside
mmcore install --test-adapters           # once: DemoCamera adapters for mmcore tests
mmcore list                              # verify: the active install must be DIV-compatible
```

| environment | what it runs |
| --- | --- |
| `lint` | `prek run --all-files`: the commit hooks, ruff included |
| `mypy-pyqt` / `mypy-pyside` | mypy against that binding |
| `tests` | `pytest -q` |

The project `.venv` still works for a quick loop (`uv run pytest -q`), but it
is not authoritative: it holds every group any `uv sync` has installed, both Qt
bindings included. Trust tox.

### The Qt binding matrix

CI type-checks against pyqt6 **and** pyside6, and runs the tests against pyqt6
alone. `mypy-pyqt` and `mypy-pyside` each sync only their own binding's group
and set `QT_API`, which is what decides the branches qtpy exposes. Bare `mypy`
diverges once both bindings are installed, and code must pass both.

`scripts/mypy_qt.py` is what the two environments call. `qtpy mypy-args` prints
the `--always-true` / `--always-false` flags for the selected binding, and
composing that with mypy needs command substitution, which `cmd.exe` lacks and
no tox `commands` line can express; the script does both in one process.

The bindings disagree on some signatures, so one annotation may not satisfy
both. `QWidget.closeEvent` takes `QCloseEvent | None` under pyqt6 and
`QCloseEvent` under pyside6: widen the override to accept `None` and guard the
`super()` call. `QWidget.style()` is optional under pyqt6 only: narrow it with
an `assert`, not a `cast` pyside6 reports as redundant.

### mypy

mypy is `strict = true` with `warn_unreachable`, and
`files = ["src", "tests", "scripts"]`, so **tests are type-checked as strictly
as the package**. Only `import-untyped`, `import-not-found` and
`no-untyped-call` are disabled; do not widen that list to silence a real
error. `redsun_mimir.services.*` also disables `misc` and `untyped-decorator`:
`fastcs` ships no `py.typed`, so every class a service takes from it is `Any`.

### prek

`prek.toml` lists the commit hooks. The same hooks run in the tox `lint` env
and in the CI `prek` job, so `uv run prek run --all-files` passing locally
means lint passes in CI. `prek` and `ruff` live in the `lint` dependency group
(included in `dev`); the ruff hooks run `uv run --locked --only-group lint`, so
the ruff version comes from `uv.lock` and `prek.toml` pins none. A hook that
rewrites a file reports failure: stage the rewrite and commit again. Do not
skip hooks with `--no-verify`.

### pytest

- `asyncio_mode = "auto"`, so **do not decorate async tests** with
  `@pytest.mark.asyncio`.
- Skip markers are public names (`needs_opengl`, `needs_mm_adapters`), imported
  by the modules using them; an underscore would only make the import look like
  a mistake.
- `filterwarnings` silences one third-party deprecation (`json_encoders`, from
  napari and useq-schema). Add a filter only for a warning this package cannot
  fix, with a comment naming its source.

### Qt and napari

Qt tests need a display. On Linux without one, set `QT_QPA_PLATFORM=offscreen`
yourself; nothing sets it for you. Use the session-scoped `qapp` fixture from
`conftest.py`; never build a `QApplication`.

`offscreen` has no OpenGL context, and napari's `QtViewer` needs a real one.
Anything constructing `ImageView` carries `needs_opengl` from `conftest.py`,
skipped unless `MIMIR_TEST_OPENGL` is set. CI provides a context with
`pyvista/setup-headless-display-action` and sets that variable, so no workflow
pins `QT_QPA_PLATFORM` for the test run.

### Micro-Manager adapters

Adapters are downloaded, not pip-installed. Their device interface version must
match the installed `pymmcore`: `mmcore list` marks a mismatched install
`(incompatible)`. Install only the test adapters (`--test-adapters`): every
mmcore device here is `adapter="DemoCamera"`, and CI installs that through
`pymmcore-plus/setup-mm-test-adapters`. Mark a test that loads a real device
with `needs_mm_adapters` from `conftest.py`, so a machine without adapters
skips it instead of failing inside `loadDevice`.

### Shell

Prefer PowerShell over `cmd.exe` for Claude Code sessions on this repo.

## Architecture invariants

- **Every user-intended device, presenter and view class appears in
  `src/redsun_mimir/redsun.yaml`**, under the right section, as
  `module.path:ClassName`. A class missing from the manifest is invisible to
  `redsun` however correct it is, and a manifest entry that does not resolve
  breaks plugin discovery for the whole bundle. A new component gets its
  manifest entry in the same commit.
- Devices are `ophyd-async` devices. Hardware access is async; no threads for
  I/O. `DeviceMap` comes from `ophyd_async.core`.
- Presenter constructors lead with exactly `(name, devices)`, view constructors
  with `(name)`. The framework checks the positional shape at discovery and the
  protocol with `isinstance` on the built instance. Do not inherit
  `PPresenter`/`PView`: property descriptors shadow instance attributes at
  runtime. Data members exposed to the framework are read-only properties.
- **The bundle writes acquisition bytes in the service owning the hardware**,
  not in the session: the camera service writes the capture window with
  `acquire-zarr`, and the device reports it with `StreamResource`/`StreamDatum`.
  Derived products go through `redsun.writers.Writer`, which `MedianPresenter`
  uses to add the scan's stack as `<detector>_scan` to the store the capture
  names. The median itself stays in memory.
- **A service is a process the session starts and stops.** It is declared in
  `redsun.yaml` under `services:`, a session file names it, and a device points
  at it with `service=`; the prefix reaches the process through its
  environment. `services/_process.py` holds what every service does around its
  `fastcs` controller.
- A signal a connector fills at connect does not exist when the device is
  constructed. So a container of such children is `ReadableDeviceMap`
  (`device/containers.py`) rather than a `DeviceMap` registered as readable,
  and `MMCamera` merges its properties into `read_configuration` itself.
- A plan collecting a `StandardDetector` pre-declares the stream with
  `bps.declare_stream(det, name=..., collect=True)` before `bps.collect`.
- Device build failures are logged and skipped; presenter and view build
  failures abort the app. A device that cannot reach its hardware fails at
  build rather than half-initialising.
- `youseetoo/` talks to real serial hardware and cannot be covered in CI. Its
  service is exercised against a `loop://` port (with `--no-reset`) and a fake
  board answering the protocol; the board itself is tested by hand (see the
  README warning).

## Code conventions

- Python >=3.11, `from __future__ import annotations` everywhere (ruff
  `FA102`).
- **Module-level names come first, after the imports:** constants, type
  aliases, `TypeVar`s and `ParamSpec`s, before any function or class. A
  reader finds every name the module is built on in one place. The one
  exception is a name built from something the module defines, such as
  `ClassPath = Annotated[str, AfterValidator(class_path)]`: it goes directly
  after that definition.
- Ruff lint has `D` (numpy docstring convention), `I`, `TC` and `PERF`
  enabled: runtime-unneeded imports go under `if TYPE_CHECKING:`. Public
  symbols need docstrings; `D100`/`D103`/`D104`/`D107` are ignored.
- Private modules are `_underscored`; each package `__init__.py` re-exports the
  public surface with an explicit `__all__`. A new public symbol goes in both
  and, if user-facing, in `redsun.yaml`.
- **Import a private module relatively, a public one absolutely.** A module
  whose dotted path has an `_underscored` part is imported as
  `from ._process import ...`; a public one as
  `from redsun_mimir.common import ...`, even from inside its own package.
  Tests import everything absolutely, since they are not part of the package.
- **The underscore marks what `__all__` cannot.** A module named `_foo.py` is
  private in its entirety, so its **module-level members carry no underscore**:
  the module name already said it. **Class members keep the underscore** on a
  class a user can reach, because `__all__` is module-scoped and cannot say
  that a method is private. A class no `__all__` re-exports is private as a
  whole, so its members drop the underscore too.
- Public methods are named in the imperative (`connect`, `set`, `launch_plan`),
  not as nouns. Nouns are for what a method returns or holds, which are
  properties.
- **`@property` is for public API only.** Private state is a plain attribute,
  computed once where it is first known (usually `__init__`); private
  behaviour is an ordinary underscored method.
- psygnal signal attributes are `sig_snake_case`, never `sigCamelCase`.
  Signals sharing a name across components are told apart by owner:
  `find_signals(container, names, owner=...)`.
- **A `__slots__` class owning a psygnal `Signal` needs `__weakref__` among its
  slots.** psygnal refers to an owner weakly and falls back silently to a
  strong reference, on which the owner is never collected.
- **Don't annotate what the assignment already says.** Annotate where mypy
  cannot infer the type (an empty container, an `Any` from `getattr`, a
  narrower declared type).
- **Don't alias an attribute to a local for a single use.** Write
  `self.main_window.show()`. A local earns its place when the value is read
  several times and reaching it costs something, when a type checker needs the
  narrowing, or when repeating the expression would hide the line.
- **No comments in the import block.** Not above an import, not above a group,
  and not to explain a `# noqa`. If a runtime import is surprising, say why at
  the annotation that needs it.
- asyncio only. Hardware goes through `ophyd-async`; Qt work stays on the Qt
  thread and crosses over through psygnal signals.
- Public API change -> docstring + `CHANGELOG.md` entry.

### Docstrings and comments

- Docstrings are concise and minimal: only the behaviour of the thing being
  defined, scoped to that definition. Write for a reader who has nothing but
  the docstring: no references to design documents, decision records or
  anything outside the immediate context.
- Don't restate the signature in prose, and don't document parameters whose
  meaning the name and type already carry. A `Parameters`, `Returns` or
  `Raises` section earns its place when it says something the signature
  cannot: units, accepted values, what `None` means, which exception and when.
- **Attributes are documented where they are declared**, by a docstring on the
  line after each one, never by a `Parameters` or `Attributes` section in the
  class docstring. This holds for everything declared as fields: dataclasses,
  `pydantic` models, `TypedDict`s, `NamedTuple`s.
- No section-divider or banner comments, and no comment blocks describing the
  code that follows. A comment earns its place only by explaining why a
  specific statement is the way it is.
- Everything committed here is scoped to this repository and assumed public:
  no local filesystem paths, no references to another project's internals.

## Testing conventions

- Tests are flat under `tests/`, one file per subsystem (`test_devices.py`,
  `test_presenters.py`, `test_views.py`, `test_services.py`,
  `test_camera.py`). Extend the existing file rather than adding a parallel
  one.
- **Test objects go at the top of the module, after the imports**: doubles,
  fixtures and helpers, before the first test. Shared fixtures and doubles
  (`FakeDetector`, `FakeFlyer`, `FakeXYStage`) belong in `conftest.py`, not
  duplicated per file. A class used by exactly one test may stay inside it.
- **All imports live at the top of the module**, in tests too. No
  function-level imports; runtime-unneeded imports go under `if TYPE_CHECKING:`.
- A test needing hardware drives it through a service, with the fixtures in
  `conftest.py` (`camera_service`, `stage_service`, `uc2_service`, and the
  devices built on them). A controller can also be driven in-process with a
  fake core or a fake serial port, needing no adapters and no PVA. A presenter
  test uses the doubles, not a service: it tests presenter logic.
- Waiting on a worker thread is an event, not a deadline: poll loops with a
  timeout fail under load and hide what broke.
- Mock hardware only. Real drivers never appear in the suite: use
  `device/_mocks.py`, ophyd-async `mock=True` connect, and the Micro-Manager
  demo adapters through `pymmcore-plus`. Anything requiring a serial port or a
  real camera is out of scope for CI.
- The example containers in `configurations/` are shipped artifacts, so
  smoke-test them with mock devices (build the container, assert its
  components come up) rather than leaving them to manual runs.
- Prefer the public interface. For a multi-step lifecycle write one happy-path
  test driving the whole sequence and asserting the observable end state, then
  small focused tests for the unhappy paths.
- Parametrize normal and edge cases together in one `@pytest.mark.parametrize`.

## Response style (agents)

- Terse. No preamble, no restatement of the request, no summary of what you
  just did.
- Show diffs, not whole files. Don't explain code unless asked.
- Don't narrate intent ("I'll now..."); just make the change.
- State assumptions in one line; ask only when genuinely blocked.
- No em dashes and no en dashes, anywhere: chat, commits, docs, docstrings,
  comments, PR and issue text. Use a plain hyphen or restructure. Arrows are
  `->` and `<-`, never `→` or `⇒`.
- `.claude/agents/*` files stay slim: scope, verify commands, and pointers to
  this file. Never restate invariants there; cross-link instead.

## Updating this guide

Say **"Update CLAUDE.md with..."** to persist a convention here. Durable,
shareable rules belong in this file, not in per-session memory.
