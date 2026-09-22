"""Typed keys for the objects this bundle shares through the virtual container.

The package owning a type declares its key. A presenter binds a value with
[`provide`][redsun.virtual.VirtualContainer.provide]; a view resolves it with
[`require`][redsun.virtual.VirtualContainer.require].

Most values are snapshots taken during ``register_providers``: later changes
travel over signals. A key holding device signals is the exception, since a
subscriber keeps hearing from them after the build.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import dependency_injector.providers as dip

if TYPE_CHECKING:
    from typing import Any

    from bluesky.protocols import Descriptor, Reading
    from ophyd_async.core import SignalR
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

#: Readback signal of every motor axis, by data key. Live, unlike the two keys
#: above: a subscriber sees every move, a plan's included.
MOTOR_READBACKS: ProviderKey[dict[str, SignalR[float]]] = dip.Dependency(
    instance_of=dict
)

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
    "MOTOR_READBACKS",
    "MOTOR_READINGS",
    "PLAN_SPECS",
]
