"""Typed keys for the objects this bundle shares through the virtual container.

A key is declared by the package that owns the type it identifies. The
presenter that computes a value binds it with
[`provide`][redsun.virtual.VirtualContainer.provide]; a view resolves it with
[`require`][redsun.virtual.VirtualContainer.require].

Every value here is a snapshot taken while the owning presenter runs
``register_providers``, and none of them tracks its source: later changes travel
over signals, not through the container.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import dependency_injector.providers as dip

if TYPE_CHECKING:
    from typing import Any

    from bluesky.protocols import Descriptor, Reading
    from redsun.virtual import ProviderKey

    from redsun_mimir.protocols import LayerSpec

#: Configuration descriptors of every detector, by data key.
DETECTOR_DESCRIPTORS: ProviderKey[dict[str, Descriptor]] = dip.Dependency(
    instance_of=dict
)

#: Current configuration readings of every detector, by data key.
DETECTOR_READINGS: ProviderKey[dict[str, Reading[Any]]] = dip.Dependency(
    instance_of=dict
)

#: Shape and dtype of the image layer each detector feeds, by device name.
DETECTOR_LAYER_SPECS: ProviderKey[dict[str, LayerSpec]] = dip.Dependency(
    instance_of=dict
)

#: Current readings of every motor axis, by data key.
MOTOR_READINGS: ProviderKey[dict[str, Reading[Any]]] = dip.Dependency(instance_of=dict)

#: Descriptors of every motor axis, by data key.
MOTOR_DESCRIPTION: ProviderKey[dict[str, Descriptor]] = dip.Dependency(instance_of=dict)

#: Current readings of every light source, by data key.
LIGHT_CONFIGURATION: ProviderKey[dict[str, Reading[Any]]] = dip.Dependency(
    instance_of=dict
)

#: Descriptors of every light source, by data key.
LIGHT_DESCRIPTION: ProviderKey[dict[str, Descriptor]] = dip.Dependency(instance_of=dict)

#: Specifiers of the plans the acquisition presenter can launch.
PLAN_SPECS: ProviderKey[set[Any]] = dip.Dependency(instance_of=set)

__all__ = [
    "DETECTOR_DESCRIPTORS",
    "DETECTOR_LAYER_SPECS",
    "DETECTOR_READINGS",
    "LIGHT_CONFIGURATION",
    "LIGHT_DESCRIPTION",
    "MOTOR_DESCRIPTION",
    "MOTOR_READINGS",
    "PLAN_SPECS",
]
