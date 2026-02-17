"""Utilities for device implementations.

`RingBuffer` has been vendored from
https://github.com/pyapp-kit/ndv and slightly adapted.
January 20, 2026.

License for the vendored `RingBuffer` code is included below.

BSD 3-Clause License

Copyright (c) 2023, Talley Lambert

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its
   contributors may be used to endorse or promote products derived from
   this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from attrs import Attribute


def convert_to_tuple(value: Iterable[float | int] | None) -> tuple[int | float, ...]:
    """Convert a value to a tuple of floats.

    If the value is ``None``, return a tuple of two zeros.
    A validator should take care of checking the actual
    value in respect to other constraints.

    Parameters
    ----------
    value : ``Any``
        Value to convert.

    Returns
    -------
    ``tuple[float, float]``
        Tuple of floats. ``(0.0, 0.0)`` if value is ``None``.

    """
    if value is None:
        return (0.0, 0.0)
    return tuple(v for v in value)


def convert_limits(
    value: dict[str, list[float]] | None,
) -> dict[str, tuple[float, ...]] | None:
    if value is None:
        return None
    return {axis: tuple(float(val) for val in limits) for axis, limits in value.items()}


def convert_to_float(value: Iterable[float]) -> tuple[float, ...]:
    """Convert a value to a tuple of floats.

    Parameters
    ----------
    value : ``Any``
        Value to convert.

    Returns
    -------
    ``tuple[float, ...]``
        Tuple of floats.

    """
    return tuple(float(val) for val in value)


def has_only_one_key(
    instance: object,
    attribute: Attribute[dict[str, dict[str, str]]],
    value: dict[str, dict[str, str]],
) -> None:
    if len(value.keys()) > 1:
        raise ValueError(
            "The first level of the nested dictionary must contain only one key."
        )


def convert_shape(value: Sequence[int]) -> tuple[int, int]:
    """Convert an input sequence to a tuple of ints.

    Used for converting the sensor shape from the configuration file.

    Parameters
    ----------
    value : ``Any``
        Value to convert.

    Returns
    -------
    ``tuple[int, ...]``
        Tuple of ints.

    """
    if len(value) != 2:
        raise ValueError("The tuple must contain exactly two values.")
    else:
        return (int(value[0]), int(value[1]))
