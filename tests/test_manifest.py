"""Integrity tests for the plugin manifest.

``src/redsun_mimir/redsun.yaml`` is the contract between this bundle and
redsun's plugin discovery: a class that is not listed is invisible, and an
entry that does not resolve breaks discovery for the whole bundle. Neither
failure mode is observable from the shipped example sessions, which
declare their components directly - which is precisely how five of the six
device entries came to name classes that no longer existed.
"""

from __future__ import annotations

import importlib
import inspect
from importlib.resources import files
from typing import TYPE_CHECKING, Any

import pytest
import yaml

import redsun_mimir.presenter
import redsun_mimir.view

if TYPE_CHECKING:
    from collections.abc import Iterator

SECTIONS = ("devices", "presenters", "views")

#: A service entry names a module and the line it prints when ready, not a
#: class, so it is checked on its own rather than walked with the rest.
MANIFEST_SECTIONS = (*SECTIONS, "services")

#: Public names that are not components: a widget a view is built from.
UNLISTED: frozenset[str] = frozenset({"SettingsControlWidget"})


def _manifest() -> dict[str, dict[str, Any]]:
    text = (files("redsun_mimir") / "redsun.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)  # type: ignore[no-any-return]


def _entries() -> Iterator[tuple[str, str, str]]:
    manifest = _manifest()
    for section in SECTIONS:
        for key, path in manifest.get(section, {}).items():
            yield section, key, path


def test_manifest_has_expected_sections() -> None:
    manifest = _manifest()
    assert set(manifest) == set(MANIFEST_SECTIONS)


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
    ("package", "section"),
    [
        (redsun_mimir.presenter, "presenters"),
        (redsun_mimir.view, "views"),
    ],
    ids=["presenters", "views"],
)
def test_every_component_is_listed(package: Any, section: str) -> None:
    """List in the manifest every presenter and view the package exports."""
    listed = {path.partition(":")[2] for path in _manifest().get(section, {}).values()}
    defined = set(package.__all__) - UNLISTED
    assert defined <= listed, (
        f"defined but missing from redsun.yaml[{section}]: {sorted(defined - listed)}"
    )
