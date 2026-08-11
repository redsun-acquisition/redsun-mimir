"""Typed keys for the objects this bundle shares through the virtual container.

A key is declared by the package that owns the type it identifies. The
presenter that computes a value binds it with
[`provide`][redsun.virtual.VirtualContainer.provide]; a view resolves it with
[`require`][redsun.virtual.VirtualContainer.require].

Most values here are snapshots taken while the owning presenter runs
``register_providers``: later changes travel over signals, not through the
container. The exception is a key holding device signals, which a consumer
subscribes to and which therefore keeps reporting after the build.
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

#: Readback signal of every motor axis, by data key. Unlike the two keys above
#: this is the live signal, so a subscriber sees every move, including the ones
#: a plan makes.
MOTOR_READBACKS: ProviderKey[dict[str, SignalR[float]]] = dip.Dependency(
    instance_of=dict
)

#: Current readings of every light source, by data key.
LIGHT_CONFIGURATION: ProviderKey[dict[str, Reading[Any]]] = dip.Dependency(
    instance_of=dict
)

#: Descriptors of every light source, by data key.
LIGHT_DESCRIPTION: ProviderKey[dict[str, Descriptor]] = dip.Dependency(instance_of=dict)

#: Current readings of every stated device, by data key.
STATED_CONFIGURATION: ProviderKey[dict[str, Reading[Any]]] = dip.Dependency(
    instance_of=dict
)

#: Descriptors of every stated device, by data key. The ``choices`` field of
#: each descriptor is what a selector is built from.
STATED_DESCRIPTION: ProviderKey[dict[str, Descriptor]] = dip.Dependency(
    instance_of=dict
)

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
    "STATED_CONFIGURATION",
    "STATED_DESCRIPTION",
]
