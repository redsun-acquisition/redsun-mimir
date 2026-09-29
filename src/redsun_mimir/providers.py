"""The types this bundle's components share values under.

A presenter returns one from a method marked with `redsun.provides`; any
component asking for the type in its constructor or `setup` receives it.

Most values are snapshots taken when the presenter is built: later changes
travel over signals.
"""

from __future__ import annotations

from typing import Any, NewType

from bluesky.protocols import Descriptor, Reading

from redsun_mimir.protocols import LayerSpec

#: Configuration descriptors of every detector, by data key.
DetectorDescriptors = NewType("DetectorDescriptors", dict[str, Descriptor])

#: Current configuration readings of every detector, by data key.
DetectorReadings = NewType("DetectorReadings", dict[str, Reading[Any]])

#: Shape and dtype of the image layer each detector feeds, by device name.
DetectorLayerSpecs = NewType("DetectorLayerSpecs", dict[str, LayerSpec])

#: Current readings of every motor axis, by data key.
MotorReadings = NewType("MotorReadings", dict[str, Reading[Any]])

#: Descriptors of every motor axis, by data key.
MotorDescription = NewType("MotorDescription", dict[str, Descriptor])

#: Current readings of every light source, by data key.
LightConfiguration = NewType("LightConfiguration", dict[str, Reading[Any]])

#: Descriptors of every light source, by data key.
LightDescription = NewType("LightDescription", dict[str, Descriptor])

__all__ = [
    "DetectorDescriptors",
    "DetectorLayerSpecs",
    "DetectorReadings",
    "LightConfiguration",
    "LightDescription",
    "MotorDescription",
    "MotorReadings",
]
