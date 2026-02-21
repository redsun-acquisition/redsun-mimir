# Storage Layer Design — sunflare migration

**Status**: Design agreed, not yet implemented
**Date**: 2026-02-21 (updated)
**Relevant repos**: sunflare, redsun-mimir, (future) ophyd-direct

---

## Context

`redsun-mimir` currently contains storage infrastructure (`Writer`, `ZarrWriter`,
`SourceInfo`) that belongs at SDK level in `sunflare`. It lives in mimir only due
to timing constraints. This document records the agreed design for migrating it.

The design was informed by studying ophyd-async's `PathProvider` / `DetectorDataLogic`
patterns, retaining what applies and diverging where mimir's requirements differ
(Python-side frame pipeline, URI-based paths for Zarr S3 support, same-backend
constraint for all devices).

---

## Core principles

1. **One shared `Writer` per session** — all devices write to the same store, each
   with its own array key. The container builds the writer once and injects it into
   every device. This is the default and only supported mode; per-device backends
   are not supported.

2. **Devices never own storage imports** — `Device` in sunflare holds a `storage`
   slot that the container fills at build time. Devices call `self.storage.*`
   without importing any storage class. If storage is not configured,
   `self.storage` is `None` and devices that require it raise explicitly at
   `prepare()` time.

3. **`StorageDescriptor` is public, lives in `sunflare.storage`** — users import
   it from there if they need it explicitly in a device class body. `Device` itself
   has no runtime import from `sunflare.storage` — the two subpackages are kept
   strictly separate. The descriptor is wired to `Device` at class definition time
   via a `TYPE_CHECKING` guard only.

4. **`StorageProxy` is the device-facing interface** — both local `Writer` instances
   and future remote proxy objects implement it. Device code is identical regardless
   of whether storage is local or remote.

5. **YAML `storage` section is optional** — when absent, `device.storage` is `None`
   for all devices. When present, `backend` is the only required key; additional
   backend-specific kwargs may be added in future without breaking the schema.

6. **Store path, filename strategy, and capacity are runtime concerns** — they are
   not part of the YAML config. Store path may come from a file dialog in the view,
   capacity from the acquisition plan parameters, and filename from a user-provided
   `FilenameProvider`. Views that want to expose these controls provide their own UI
   for them. The `FilenameProvider` and `PathProvider` abstractions in
   `sunflare.storage` are available for this purpose.

7. **Remote devices write autonomously** — the future `RemoteStorageProxy` forwards
   `PathInfo` (picklable) to the remote process, which constructs its own local
   `Writer`. Stream docs are sent back to the central process. Device code is
   unchanged — `self.storage.prepare(...)` works identically on both sides.

---

## Agreed architecture

### Layer responsibilities

| Layer | Owns |
|---|---|
| **sunflare** | `Writer` (ABC), `ZarrWriter`, `StorageProxy` (protocol), `StorageDescriptor`, `PathInfo`, `FilenameProvider` (protocol), `PathProvider` (protocol), `StaticFilenameProvider`, `UUIDFilenameProvider`, `AutoIncrementFilenameProvider`, `StaticPathProvider` |
| **ophyd-direct** (future) | `RemoteStorageProxy` — implements `StorageProxy`, serialises `PathInfo` to remote process, receives stream docs back |
| **redsun-mimir** | Application layer only: scan plans, UI, `StorageConfig` YAML schema, container wiring that builds the `Writer` and injects it into devices |

### New `sunflare.storage` subpackage

```
sunflare/storage/
    __init__.py       # public exports
    _base.py          # Writer (ABC), SourceInfo, SinkGenerator — moved from mimir verbatim
    _zarr.py          # ZarrWriter — moved from mimir verbatim
    _path.py          # PathInfo, FilenameProvider (protocol), PathProvider (protocol),
                      # StaticFilenameProvider, UUIDFilenameProvider,
                      # AutoIncrementFilenameProvider, StaticPathProvider
    _proxy.py         # StorageProxy (protocol), StorageDescriptor (descriptor class)
```

### `StorageProxy` protocol (`sunflare/storage/_proxy.py`)

The minimal interface that device code calls. Both `Writer` and future
`RemoteStorageProxy` implement it:

```python
class StorageProxy(Protocol):
    def update_source(
        self, name: str, dtype: np.dtype, shape: tuple[int, ...]
    ) -> None: ...
    def prepare(self, name: str, capacity: int = 0) -> SinkGenerator: ...
    def kickoff(self) -> None: ...
    def complete(self, name: str) -> None: ...
    def get_indices_written(self, name: str | None = None) -> int: ...
    def collect_stream_docs(
        self, name: str, indices_written: int
    ) -> Iterator[StreamAsset]: ...
```

Note: `prepare()` no longer takes `store_path` — path resolution happens inside
the `Writer` via its injected `PathProvider`. Devices have no path knowledge.

### `StorageDescriptor` (`sunflare/storage/_proxy.py`)

A public descriptor class that manages the `storage` slot on `Device`:

```python
class StorageDescriptor:
    def __get__(self, obj, objtype=None) -> StorageProxy | None:
        if obj is None:
            return self
        return obj.__dict__.get("_storage", None)

    def __set__(self, obj, value: StorageProxy | None) -> None:
        obj.__dict__["_storage"] = value
```

`Device` in `sunflare.device` holds this descriptor with no runtime import
from `sunflare.storage`. The descriptor instance is attached to `Device` by
`sunflare.storage` at import time, keeping the dependency one-directional:
`sunflare.storage` -> `sunflare.device`, never the reverse.

```python
# sunflare/device/_base.py
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sunflare.storage import StorageProxy

class Device(PDevice, abc.ABC):
    storage: StorageProxy | None  # type annotation only; descriptor attached
                                  # by sunflare.storage at import time
```

### `PathInfo` (`sunflare/storage/_path.py`)

URI-based rather than filesystem-path-based (unlike ophyd-async) to support
Zarr's S3 and other non-POSIX backends:

```python
@dataclass
class PathInfo:
    store_uri: str        # e.g. "file:///data/scan001.zarr" or "s3://bucket/scan001.zarr"
    array_key: str        # per-device key within the store, defaults to device name
    capacity: int = 0     # max frames, 0 = unlimited
    mimetype_hint: str = "application/x-zarr"
```

`PathInfo` is intentionally extensible — OME-Zarr will need physical units,
axis types, and coordinate metadata. Future fields go here or in an
`extra: dict[str, Any]` field that backend-specific writers consume.

### `FilenameProvider` and `PathProvider` (`sunflare/storage/_path.py`)

Composable callables, matching ophyd-async's pattern:

```python
class FilenameProvider(Protocol):
    def __call__(self, device_name: str | None = None) -> str: ...

class PathProvider(Protocol):
    def __call__(self, device_name: str | None = None) -> PathInfo: ...
```

Concrete implementations: `StaticFilenameProvider`, `UUIDFilenameProvider`,
`AutoIncrementFilenameProvider`, `StaticPathProvider`.

These are available for views that want to expose filename/path controls to the
user. The container uses them internally to resolve paths at scan time.

### YAML storage configuration

The `storage` section is optional. When absent, `device.storage` is `None` for
all devices. When present, `backend` is the only required key. Additional
backend-specific kwargs may appear alongside `backend` in future:

```yaml
# storage absent — device.storage is None for all devices

# minimal:
storage:
  backend: zarr

# future backends with additional kwargs:
storage:
  backend: hdf5
  swmr: true        # backend-specific; ignored by other backends
```

Supported `backend` values (current): `zarr`
Planned: `hdf5`, `ome-zarr`, `tiff`

Store path, filename, and capacity are **not** in the YAML. They are provided
at scan time:
- **Store path**: file dialog in the view, or programmatically by the scan plan
- **Filename**: user-provided `FilenameProvider` (default: `UUIDFilenameProvider`)
- **Capacity**: acquisition plan parameters (default: `0` = unlimited)

---

## OME-Zarr considerations (future `OMEZarrWriter`)

OME-Zarr imposes a strict metadata schema on top of Zarr v3:
- `multiscales` with `axes` (name, type, unit)
- `coordinateTransformations` (scale, translation per axis)

**Design constraint to respect now**: keep `SourceInfo` extensible.
Physical units, axis semantics, and coordinate metadata must be attachable
to a source without changing the base `Writer` interface.
Approach: `SourceInfo` gets an optional `extra: dict[str, Any] = field(default_factory=dict)`
that `OMEZarrWriter` reads and base `Writer` ignores.

---

## Migration plan

### PR 1 — sunflare: add `sunflare.storage`

- Move `Writer`, `SourceInfo`, `SinkGenerator` from mimir -> `sunflare/storage/_base.py`
- Move `ZarrWriter` from mimir -> `sunflare/storage/_zarr.py`
- Add `PathInfo`, `FilenameProvider`, `PathProvider`, concrete implementations -> `_path.py`
- Add `StorageProxy` protocol and `StorageDescriptor` -> `_proxy.py`
- Attach `StorageDescriptor` instance to `Device` from within `sunflare.storage`
  on import (no reverse runtime import into `sunflare.device`)
- Update `Writer.prepare()` signature: remove `store_path` param; path resolution
  is handled internally via `PathProvider` injected at writer construction
- No other behaviour changes to `Writer` or `ZarrWriter`
- Tests for all new types
- Bump to `sunflare 0.11.0`

### PR 2 — mimir: update devices + deprecation shims

- Update `pyproject.toml`: require `sunflare >= 0.11.0`
- Devices: remove `ZarrWriter.get()`, change `self._writer.*` -> `self.storage.*`,
  remove `store_path` from `PrepareKwargs`
- `redsun_mimir/storage/base.py` and `_zarr.py` -> re-export from `sunflare.storage`
  with `DeprecationWarning`
- Update device tests: inject mock `StorageProxy` instead of using the registry

### PR 3 — mimir: container wiring + remove legacy storage

- Add `StorageConfig` parsing in the container build phase
- Container: if `storage:` present in YAML, build `Writer` from `backend` key,
  inject into all devices via `device.storage = writer`
- `PrepareKwargs` loses `store_path` across the board
- Delete `redsun_mimir/storage/` entirely
- Update acquisition YAMLs
- Full integration tests

---

## Remote device path (future, post ophyd-direct)

When `RemoteStorageProxy` is added to `sunflare.storage` (or ophyd-direct):
- Container detects remote device, injects `RemoteStorageProxy` instead of `Writer`
- Proxy serialises `PathInfo` to the remote process on `prepare()`
- Remote process constructs a local `ZarrWriter`, writes autonomously
- Proxy receives stream docs back and forwards them to the RunEngine
- Device code is unchanged — `self.storage.prepare(...)` is identical

---

## Comparison with ophyd-async

| Concern | ophyd-async | sunflare/mimir |
|---|---|---|
| Path info | `directory_path: PurePath` + `filename: str` | `store_uri: str` (URI-based, S3-compatible) |
| Storage ownership | Per-device `DataLogic` strategy | Shared `Writer` injected via descriptor |
| Device interface | `DataLogic.prepare_unbounded()` | `self.storage.prepare()` |
| Filename strategy | `FilenameProvider` composable | Same pattern, adopted verbatim |
| Path strategy | `PathProvider` composable | Same pattern, adopted verbatim |
| Remote support | Built-in (EPICS hardware writes) | Future `RemoteStorageProxy` |
| Backend selection | Per-device (HDF5, TIFF, JPEG) | Per-session, single backend |

---

## Key design decisions (agreed)

1. **`StorageProxy` not `Writer` is injected** — `StorageProxy` is the protocol;
   `Writer` implements it locally, `RemoteStorageProxy` implements it remotely
2. **One store, multiple array keys** — all devices write to same backend store,
   each with own key; Zarr v3 / acquire-zarr supports concurrent writers
3. **`ZarrWriter` moves to sunflare** — not mimir-specific, belongs at SDK level
4. **OME-Zarr is a future backend** — `SourceInfo.extra` dict keeps door open
5. **Network devices write autonomously** — central process receives stream docs only
6. **ophyd-direct is a separate future package** — sunflare/mimir don't depend on it
7. **`storage` section is optional in YAML** — `backend` is the only required key
   when the section is present
8. **Path, filename, capacity are runtime** — not in YAML, provided at scan time
   or via UI using `FilenameProvider` / `PathProvider` from `sunflare.storage`
9. **`sunflare.storage` and `sunflare.device` are strictly separate at runtime** —
   descriptor attached from the storage side on import, never the reverse
10. **`Writer.get()` registry deleted** — injection via container replaces
    service location entirely
