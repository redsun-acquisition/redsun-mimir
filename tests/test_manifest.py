"""Integrity tests for the plugin manifest.

``src/redsun_mimir/redsun.yaml`` is the contract between this bundle and
redsun's plugin discovery: a class that is not listed is invisible, and an
entry that does not resolve breaks discovery for the whole bundle. Neither
failure mode is observable from the shipped example containers, which
declare their components directly - which is precisely how five of the six
device entries came to name classes that no longer existed.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from importlib.resources import files
from typing import TYPE_CHECKING, Any

import pytest
import yaml
from redsun.presenter import Presenter
from redsun.view.qt import QtView

import redsun_mimir.presenter
import redsun_mimir.view

if TYPE_CHECKING:
    from collections.abc import Iterator

SECTIONS = ("devices", "presenters", "views")

#: Classes that are deliberately absent from the manifest: abstract bases and
#: components composed inside another device rather than declared top-level.
UNLISTED: frozenset[str] = frozenset(
    {
        "MMBaseCameraDevice",
    }
)


def _manifest() -> dict[str, dict[str, str]]:
    text = (files("redsun_mimir") / "redsun.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)  # type: ignore[no-any-return]


def _entries() -> Iterator[tuple[str, str, str]]:
    manifest = _manifest()
    for section in SECTIONS:
        for key, path in manifest.get(section, {}).items():
            yield section, key, path


def _public_classes(package: Any, base: type) -> dict[str, type]:
    """Return every concrete *base* subclass defined inside *package*."""
    found: dict[str, type] = {}
    for info in pkgutil.walk_packages(package.__path__, f"{package.__name__}."):
        module = importlib.import_module(info.name)
        found.update(
            {
                name: obj
                for name, obj in vars(module).items()
                if inspect.isclass(obj)
                and issubclass(obj, base)
                and obj is not base
                and obj.__module__.startswith(package.__name__)
                and not name.startswith("_")
            }
        )
    return found


def test_manifest_has_expected_sections() -> None:
    manifest = _manifest()
    assert set(manifest) == set(SECTIONS)


@pytest.mark.parametrize(
    ("section", "key", "path"),
    [pytest.param(s, k, p, id=f"{s}:{k}") for s, k, p in _entries()],
)
def test_manifest_entry_resolves(section: str, key: str, path: str) -> None:
    """Every dotted path in the manifest imports and yields a class."""
    module_path, _, class_name = path.partition(":")
    assert class_name, f"{section}:{key} is not in 'module.path:ClassName' form"

    module = importlib.import_module(module_path)
    obj = getattr(module, class_name, None)
    assert obj is not None, f"{path} - {class_name!r} not found in {module_path}"
    assert inspect.isclass(obj), f"{path} does not name a class"


@pytest.mark.parametrize(
    ("package", "base", "section"),
    [
        (redsun_mimir.presenter, Presenter, "presenters"),
        (redsun_mimir.view, QtView, "views"),
    ],
    ids=["presenters", "views"],
)
def test_every_component_is_listed(package: Any, base: type, section: str) -> None:
    """No presenter or view ships without a manifest entry."""
    listed = {path.partition(":")[2] for path in _manifest().get(section, {}).values()}
    defined = set(_public_classes(package, base)) - UNLISTED
    assert defined <= listed, (
        f"defined but missing from redsun.yaml[{section}]: {sorted(defined - listed)}"
    )
