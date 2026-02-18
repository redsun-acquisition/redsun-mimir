# Storage Layer Design — sunflare migration

**Status**: Design agreed, not yet implemented
**Date**: 2026-02-18
**Relevant repos**: sunflare, redsun-mimir, (future) ophyd-direct

---

## Context

`redsun-mimir` currently contains storage infrastructure (`Writer`, `ZarrWriter`,
`SourceInfo`) that belongs at SDK level in `sunflare`. It lives in mimir only due
to timing constraints. This document records the agreed design for migrating it.

---

## Agreed architecture

### Layer responsibilities

| Layer | Owns |
|---|---|
| **sunflare** | `Writer` (abstract), `ZarrWriter`, future `HDF5Writer` / `OMEZarrWriter`, `PathProvider` protocol, `PathInfo`, `WritableDevice` mixin |
| **ophyd-direct** (future) | Process/network transport, device proxies, forwards `PathInfo` to remote devices |
| **redsun-mimir** | Application layer only: scan plans, UI, `StorageConfig` YAML schema, container wiring |

### New `sunflare.storage` subpackage

```
sunflare/storage/
    __init__.py      # public exports
    _base.py         # Writer (ABC), SourceInfo, SinkGenerator — moved from mimir verbatim
    _zarr.py         # ZarrWriter — moved from mimir verbatim
    _path.py         # PathProvider protocol, PathInfo dataclass, StaticPathProvider
```

### `PathProvider` protocol (`sunflare/storage/_path.py`)

A **picklable callable** — the only thing injected at app level.

```python
@dataclass
class PathInfo:
    store_uri: str          # e.g. "file:///data/scan001.zarr" or "s3://bucket/scan001.zarr"
    array_key: str          # per-device key within the store, defaults to device name
    capacity: int           # max frames, 0 = unlimited
    mimetype_hint: str      # e.g. "application/x-zarr"

class PathProvider(Protocol):
    def __call__(self, device_name: str) -> PathInfo: ...
```

`PathInfo` is intentionally extensible — OME-Zarr will need physical units,
axis types, and coordinate metadata attached here.

### `WritableDevice` mixin (`sunflare/device/_writable.py`)

```python
class WritableDevice(Device):
    path_provider: PathProvider | None = None
```

- The container detects `isinstance(device, WritableDevice)` at build time
- Injects a shared `PathProvider` instance (not a `Writer` instance)
- Each device constructs its own `Writer` at `prepare()` time by calling
  `self.path_provider(self.name)` — this is what makes cross-process work

### Why PathProvider, not Writer, is injected

Injecting a live `Writer` (with open file handles, generator state) breaks the
cross-process model — it can't be pickled. A `PathProvider` is a pure config
callable: picklable, stateless between calls, safe to send to a subprocess.

Each device owns its own `Writer` instance, constructed from `PathInfo`.
Multiple devices can write to the **same store path** with **different array keys**
— acquire-zarr / Zarr v3 supports multiple independent writers to the same store
(confirmed working).

### Storage location policy

| Device location | Writer location | Mechanism |
|---|---|---|
| Same process | Same process | Direct construction from `PathInfo` |
| Same workstation, different process | Each subprocess | `PathInfo` forwarded via ophyd-direct transport; each process constructs its own `Writer`; Zarr store is on shared local filesystem |
| Remote/network | Remote process | `PathInfo` forwarded; remote device writes to its own local path or a shared network path (e.g. NFS, S3); central process receives `StreamResource` docs only — never touches bytes |

For network devices at significant data rates, the remote device writes
autonomously and reports `StreamResource` / `StreamDatum` documents back.
The central process tracks *what* was written and *where*, not the bytes.

---

## OME-Zarr considerations (future `OMEZarrWriter`)

OME-Zarr imposes a strict metadata schema on top of Zarr v3:
- `multiscales` with `axes` (name, type, unit)
- `coordinateTransformations` (scale, translation per axis)

A device's canonical `prefix:name\property` keys (e.g. `X_step_size`, `egu`)
won't map directly to OME axes. Translation helpers will be needed.

**Design constraint to respect now**: keep `SourceInfo` extensible.
Physical units, axis semantics, and coordinate metadata must be attachable
to a source without changing the base `Writer` interface.
Likely approach: `SourceInfo` gets an optional `extra: dict[str, Any] = field(default_factory=dict)`
that `OMEZarrWriter` reads and base `Writer` ignores.

---

## Migration plan

### Step 1 — sunflare PR: add `sunflare.storage`
- Move `Writer`, `SourceInfo`, `SinkGenerator` from mimir → `sunflare/storage/_base.py`
- Move `ZarrWriter` from mimir → `sunflare/storage/_zarr.py`
- Add `PathProvider`, `PathInfo`, `StaticPathProvider` → `sunflare/storage/_path.py`
- Add `WritableDevice` mixin → `sunflare/device/_writable.py`
- No behaviour changes — pure relocation

### Step 2 — mimir PR: update imports + deprecation shims
- `redsun_mimir/storage/base.py` → re-exports from `sunflare.storage` with deprecation warning
- `redsun_mimir/storage/_zarr.py` → same
- Devices (`mmcore/_devices.py`, `pseudo/_devices.py`) updated to:
  - Inherit `WritableDevice`
  - Use `self.path_provider` instead of `ZarrWriter.get("zarr-writer")`
  - Construct writer at `prepare()` time

### Step 3 — mimir PR: container wiring
- Add `StorageConfig` to app YAML schema
- Container builds `PathProvider` from config, injects into `WritableDevice` instances
- Remove service-locator `ZarrWriter.get()` pattern entirely

---

## Current state of mimir storage (as of 2026-02-18)

- `src/redsun_mimir/storage/base.py` — `Writer` ABC, `SourceInfo` dataclass
- `src/redsun_mimir/storage/_zarr.py` — `ZarrWriter` using `acquire_zarr`
- Devices use service locator: `self._writer = ZarrWriter.get("zarr-writer")`
- Two devices use the writer: `device/mmcore/_devices.py:186`, `device/pseudo/_devices.py:102`

---

## Key design decisions (already agreed)

1. **`PathProvider` is injected, not `Writer`** — writer is per-device, constructed at prepare time
2. **One store, multiple array keys** — all devices write to same Zarr store, each with own key
3. **ZarrWriter moves to sunflare** — not mimir-specific, belongs at SDK level
4. **OME-Zarr is a future backend** — `SourceInfo.extra` dict keeps door open
5. **Network devices write autonomously** — central process receives stream docs only
6. **ophyd-direct is a separate future package** — sunflare/mimir don't depend on it

---

## ophyd-async reference

Studied as prior art. Key patterns borrowed:
- `PathProvider` protocol (callable returning path config)
- `PathInfo` dataclass
- `DetectorDataLogic` composition pattern → maps to `WritableDevice` mixin
- Per-device writer construction at `prepare()` time

Key difference from ophyd-async: in mimir frames pass through Python (generator
`send()`); in ophyd-async bytes flow through EPICS AD pipeline. The `Writer`
in sunflare is doing what `NDFileHDF5IO` hardware does in ophyd-async.
