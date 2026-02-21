# Storage Layer Design — sunflare migration

**Status**: PR 1 (sunflare.storage) complete; PR 2 and PR 3 pending
**Date**: 2026-02-21
**Relevant repos**: sunflare, redsun-mimir, (future) ophyd-direct

---

## Context

`redsun-mimir` originally contained storage infrastructure (`Writer`,
`ZarrWriter`, `SourceInfo`) that belongs at SDK level in `sunflare`.
PR 1 has been merged into `sunflare` on the `feat/storage` branch.
This document reflects the finalised design as implemented.

---

## Core principles

1. **One shared `Writer` per session** — all devices write to the same
   store, each with its own array key.  The container builds the writer
   once and injects it into every device that declares a `storage`
   attribute.

2. **Storage is opt-in per device** — devices that need storage declare
   `storage = StorageDescriptor()` in their class body.  The base
   `Device` class has no storage attribute.  The container injects the
   shared writer into any device that has the attribute.

3. **`StorageProxy` is the device-facing interface** — both local
   `Writer` instances and future remote proxy objects implement it.
   Device code is identical regardless of whether storage is local or
   remote.

4. **Backend classes are internal** — `ZarrWriter` and future backends
   are not exported from `sunflare.storage`.  The container selects and
   instantiates the correct backend from the session YAML; importing a
   backend directly is not a supported use case.

5. **Backend dependencies are optional extras** — `acquire-zarr` is not
   a core dependency of sunflare.  Install `sunflare[zarr]` to use
   `ZarrWriter`.  Future backends follow the same pattern.

6. **Store path, filename, and capacity are runtime concerns** — not
   part of the YAML config.  Store path comes from a file dialog or scan
   plan; filename from a `FilenameProvider`; capacity from acquisition
   plan parameters.

7. **Remote devices write autonomously** — the future
   `RemoteStorageProxy` forwards `PathInfo` (picklable) to the remote
   process, which constructs its own local `Writer`.  Stream docs are
   sent back.  Device code is unchanged.

---

## Implemented architecture (PR 1)

### Layer responsibilities

| Layer | Owns |
|---|---|
| **sunflare** | `Writer` (ABC), `FrameSink`, `SourceInfo`, `StorageProxy` (protocol), `StorageDescriptor`, `PathInfo`, `FilenameProvider`, `PathProvider`, concrete filename/path providers |
| **sunflare** (internal) | `ZarrWriter` — internal, not exported; future `HDF5Writer`, `OMEZarrWriter` follow the same pattern |
| **ophyd-direct** (future) | `RemoteStorageProxy` — implements `StorageProxy`, serialises `PathInfo` to remote process, receives stream docs back |
| **redsun-mimir** | Application layer: scan plans, UI, `StorageConfig` YAML schema, container wiring that selects and instantiates the backend |

### `sunflare.storage` public API

```
sunflare/storage/
    __init__.py    # exports below only — no backend classes
    _base.py       # Writer (ABC), FrameSink, SourceInfo
    _path.py       # PathInfo, FilenameProvider, PathProvider,
                   # StaticFilenameProvider, UUIDFilenameProvider,
                   # AutoIncrementFilenameProvider, StaticPathProvider
    _proxy.py      # StorageProxy (protocol), StorageDescriptor
    _zarr.py       # ZarrWriter — internal, requires sunflare[zarr]
```

Public exports from `sunflare.storage`:
`Writer`, `FrameSink`, `SourceInfo`, `PathInfo`, `FilenameProvider`,
`PathProvider`, `StaticFilenameProvider`, `UUIDFilenameProvider`,
`AutoIncrementFilenameProvider`, `StaticPathProvider`,
`StorageProxy`, `StorageDescriptor`

### `FrameSink`

Returned by `Writer.prepare()`. Devices write frames via
`sink.write(frame)` and signal completion via `sink.close()`.
Holds a back-reference to the writer and calls `_write_frame()` under
the writer lock. No generator machinery.

```python
class FrameSink:
    def write(self, frame: npt.NDArray[np.generic]) -> None: ...
    def close(self) -> None: ...  # delegates to Writer.complete(name)
```

### `StorageDescriptor`

Public descriptor class. Devices opt in by declaring it in their class
body:

```python
from sunflare.storage import StorageDescriptor, StorageProxy

class MyDetector(Device):
    storage = StorageDescriptor()
```

The container then injects the shared writer at build time:

```python
device.storage = writer  # writer satisfies StorageProxy
```

### `StorageProxy` protocol

The interface devices call. `Writer` satisfies it structurally.
Future `RemoteStorageProxy` will too.

```python
class StorageProxy(Protocol):
    def update_source(self, name: str, dtype: np.dtype, shape: tuple[int, ...],
                      extra: dict | None = None) -> None: ...
    def prepare(self, name: str, capacity: int = 0) -> FrameSink: ...
    def kickoff(self) -> None: ...
    def complete(self, name: str) -> None: ...
    def get_indices_written(self, name: str | None = None) -> int: ...
    def collect_stream_docs(self, name: str, indices_written: int) -> Iterator[StreamAsset]: ...
```

Note: `StorageProxy` does not implement Bluesky's `Flyable` or
`Preparable` protocols — that is the device's responsibility.
The shared names (`kickoff`, `complete`) are coincidental; the
signatures differ (`complete(name)` vs `complete()`).

### `PathInfo` and providers

URI-based (not filesystem-path-based) to support S3 and other
non-POSIX backends:

```python
@dataclass
class PathInfo:
    store_uri: str        # "file:///data/scan.zarr" or "s3://bucket/scan.zarr"
    array_key: str        # per-device key within the store
    capacity: int = 0     # 0 = unlimited
    mimetype_hint: str = "application/x-zarr"
    extra: dict = {}      # backend-specific metadata (e.g. OME-Zarr axes)
```

Composable providers:

```python
# Static filename, UUID per acquisition, or auto-incrementing
StaticFilenameProvider("scan001")
UUIDFilenameProvider()
AutoIncrementFilenameProvider(base="scan", max_digits=5)

# Compose with a base URI to produce PathInfo
StaticPathProvider(UUIDFilenameProvider(), base_uri="file:///data")
```

### YAML storage configuration (PR 3)

The `storage` section is optional. When absent, `device.storage` is
`None` for all devices. When present, `backend` is the only required
key:

```yaml
# absent — no storage for this session

# minimal:
storage:
  backend: zarr

# future backends with additional kwargs:
storage:
  backend: hdf5
  swmr: true
```

Supported `backend` values (current): `zarr`
Planned: `hdf5`, `ome-zarr`, `tiff`

---

## OME-Zarr considerations (future)

`SourceInfo.extra: dict[str, Any]` keeps the door open — an
`OMEZarrWriter` reads axis labels, physical units, and coordinate
transforms from `extra`; the base `Writer` ignores it.

---

## Migration plan

### PR 1 — sunflare: `sunflare.storage` ✅ complete

Branch: `feat/storage`

- `Writer` ABC, `FrameSink`, `SourceInfo` in `_base.py`
- `PathInfo`, `FilenameProvider`, `PathProvider`, concrete providers in `_path.py`
- `StorageProxy` protocol, `StorageDescriptor` in `_proxy.py`
- `ZarrWriter` (internal, requires `sunflare[zarr]`) in `_zarr.py`
- `acquire-zarr` is an optional extra, not a core dependency
- 37 smoke tests, mypy strict clean

### PR 2 — mimir: update devices + deprecation shims

Branch: `feat/storage-migration`
Depends on: PR 1 merged + `sunflare 0.11.0` released

- Add `storage = StorageDescriptor()` to `MmcoreDetector` and `PseudoDetector`
- Remove `self._writer = ZarrWriter.get("zarr-writer")` from `__init__`
- Replace `self._writer.*` with `self.storage.*`
- Remove `store_path` from `PrepareKwargs` — devices no longer decide where to write
- Guard at top of `prepare()`: `if self.storage is None: raise RuntimeError(...)`
- Add deprecation shims in `redsun_mimir/storage/` re-exporting from `sunflare.storage`
- Update device tests: inject mock `StorageProxy` instead of `ZarrWriter` registry

### PR 3 — mimir: container wiring + remove legacy storage

Branch: `feat/storage-container`
Depends on: PR 2

- Parse optional `storage:` section from YAML
- Container build phase: if `storage:` present, lazy-import backend, construct
  shared `Writer` with a `PathProvider`, inject into all devices that have
  `storage` attribute
- Delete `redsun_mimir/storage/` entirely
- Update acquisition YAMLs
- Integration test: one writer, two devices, same store, different array keys

---

## Remote device path (future, post ophyd-direct)

`RemoteStorageProxy` added to `sunflare.storage` (or ophyd-direct):
- Implements `StorageProxy` — container injects it like any other writer
- `prepare()` serialises `PathInfo` to remote process
- Remote process constructs local `Writer`, writes autonomously
- Proxy receives stream docs back, forwards to RunEngine
- Device code unchanged

---

## What changed from the original design

| Original | Current |
|---|---|
| `PathProvider` injected into devices | Shared `Writer` injected; writer holds `PathProvider` internally |
| `WritableDevice` mixin | Opt-in `storage = StorageDescriptor()` per device |
| `SinkGenerator` (generator with `send()`) | `FrameSink` with `write()` / `close()` |
| `ZarrWriter` public export | Internal only; container does lazy import |
| Per-device `Writer` constructed at `prepare()` time | One shared `Writer` per session |
