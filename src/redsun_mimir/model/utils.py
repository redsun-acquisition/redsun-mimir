"""Numpy Ring Buffer.

Vendored from https://github.com/pyapp-kit/ndv
and slightly adapted.
January 20, 2026.

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

import threading
import warnings
from collections.abc import Iterator, Sequence
from typing import TYPE_CHECKING, Any, overload

import numpy as np
import numpy.typing as npt
from psygnal import Signal

if TYPE_CHECKING:
    from typing import Callable, SupportsIndex

__all__ = ["RingBuffer"]


class RingBuffer(Sequence[npt.NDArray[Any]]):
    """Ring buffer structure with a given capacity and element type.

    Parameters
    ----------
    max_capacity: int
        The maximum capacity of the ring buffer.
    dtype: npt.DTypeLike
        Desired type (and shape) of individual buffer elements.
        This is passed to `np.empty`, so it can be any
        [dtype-like object](https://numpy.org/doc/stable/reference/arrays.dtypes.html).
        Common scenarios will be:
            - a fixed dtype (e.g. `int`, `np.uint8`, `'u2'`, `np.dtype('f4')`)
            - a `(fixed_dtype, shape)` tuple (e.g. `('uint16', (512, 512))`)
    allow_overwrite: bool
        If false, throw an IndexError when trying to append to an already full
        buffer. Defaults to True.
    create_buffer: Callable[[int, npt.DTypeLike], npt.NDArray]
        A callable that creates the underlying array.
        May be used to customize the initialization of the array. Defaults to
        `np.empty`.

    Notes
    -----
    Vendored from [numpy-ringbuffer](https://github.com/eric-wieser/numpy_ringbuffer),
    by Eric Wieser (MIT License).  And updated with typing and signals.

    This implementation is thread-safe.
    Locks are held only during index manipulation,
    not during expensive array operations, to minimize contention.
    """

    resized = Signal(int)

    def __init__(
        self,
        max_capacity: int,
        dtype: npt.DTypeLike = float,
        *,
        allow_overwrite: bool = True,
        create_buffer: Callable[[int, npt.DTypeLike], npt.NDArray[Any]] = np.empty,
    ) -> None:
        self._arr = create_buffer(max_capacity, dtype)
        self._left_index = 0
        self._right_index = 0
        self._capacity = max_capacity
        self._allow_overwrite = allow_overwrite
        self._lock = threading.RLock()

    # -------------------- Properties --------------------

    @property
    def is_full(self) -> bool:
        """True if there is no more space in the buffer."""
        with self._lock:
            return len(self) == self._capacity

    @property
    def dtype(self) -> np.dtype[Any]:
        """Return the dtype of the buffer."""
        return self._arr.dtype

    @property
    def shape(self) -> tuple[int, ...]:
        """Return the shape of the valid buffer (excluding unused space)."""
        with self._lock:
            return (len(self), *self._arr.shape[1:])

    @property
    def itemshape(self) -> tuple[int, int]:
        """Return the shape of individual items in the buffer."""
        return self._arr.shape[1], self._arr.shape[2]

    # these mirror methods from deque
    @property
    def maxlen(self) -> int:
        """Return the maximum capacity of the buffer."""
        return self._capacity

    # -------------------- Methods --------------------

    def append(self, value: npt.ArrayLike) -> None:
        """Append a value to the right end of the buffer.

        Thread-safe for single producer scenarios. The lock is only held
        during index manipulation, not during the array write.
        """
        # Determine the write index and update state atomically
        with self._lock:
            was_full = len(self) == self._capacity
            if was_full:
                if not self._allow_overwrite:
                    raise IndexError(
                        "append to a full RingBuffer with overwrite disabled"
                    )
                elif not len(self):
                    return
                else:
                    self._left_index += 1

            write_index = self._right_index % self._capacity
            self._right_index += 1
            self._fix_indices()

        # Perform the expensive array write outside the lock
        self._arr[write_index] = value

        # Emit signal outside the lock to avoid callback deadlocks
        if not was_full:
            self.resized.emit(len(self))

    def appendleft(self, value: npt.ArrayLike) -> None:
        """Append a value to the left end of the buffer.

        Thread-safe for producer scenarios. The lock is only held
        during index manipulation, not during the array write.
        """
        # Determine the write index and update state atomically
        with self._lock:
            was_full = len(self) == self._capacity
            if was_full:
                if not self._allow_overwrite:
                    raise IndexError(
                        "append to a full RingBuffer with overwrite disabled"
                    )
                elif not len(self):
                    return
                else:
                    self._right_index -= 1

            self._left_index -= 1
            self._fix_indices()
            write_index = self._left_index

        # Perform the expensive array write outside the lock
        self._arr[write_index] = value

        # Emit signal outside the lock to avoid callback deadlocks
        if not was_full:
            self.resized.emit(len(self))

    def pop(self) -> npt.NDArray[Any]:
        """Pop a value from the right end of the buffer.

        Thread-safe for consumer scenarios. The lock is only held during
        index manipulation, array copy happens outside the lock.
        """
        # Atomically get the read index and update state
        with self._lock:
            if len(self) == 0:
                raise IndexError("pop from an empty RingBuffer")
            self._right_index -= 1
            self._fix_indices()
            read_index = self._right_index % self._capacity
            new_len = len(self)

        # Copy the array data outside the lock
        res: npt.NDArray[Any] = self._arr[read_index].copy()

        # Emit signal outside the lock
        self.resized.emit(new_len)
        return res

    def popleft(self) -> npt.NDArray[Any]:
        """Pop a value from the left end of the buffer.

        Thread-safe for consumer scenarios. The lock is only held during
        index manipulation, array copy happens outside the lock.
        """
        # Atomically get the read index and update state
        with self._lock:
            if len(self) == 0:
                raise IndexError("pop from an empty RingBuffer")
            read_index = self._left_index
            self._left_index += 1
            self._fix_indices()
            new_len = len(self)

        # Copy the array data outside the lock
        res: npt.NDArray[Any] = self._arr[read_index].copy()

        # Emit signal outside the lock
        self.resized.emit(new_len)
        return res

    def peek(self) -> npt.NDArray[Any]:
        """Peek at the value at the right end of the buffer without removing it.

        Thread-safe for visualization scenarios. The lock is only held to
        calculate the read index, array copy happens outside the lock.
        This minimizes blocking for periodic visualization access.
        """
        # Atomically get the read index
        with self._lock:
            if len(self) == 0:
                raise IndexError("peek from an empty RingBuffer")
            read_index = (self._right_index - 1) % self._capacity

        # Copy the array data outside the lock to minimize contention
        res: npt.NDArray[Any] = self._arr[read_index].copy()
        return res

    def extend(self, values: npt.ArrayLike) -> None:
        """Extend the buffer with the given values."""
        with self._lock:
            values = np.asarray(values)
            lv = len(values)
            if len(self) + lv > self._capacity:
                if not self._allow_overwrite:
                    raise IndexError(
                        "Extending a RingBuffer such that it would overflow, "
                        "with overwrite disabled."
                    )
                elif not len(self):
                    return
            if lv >= self._capacity:
                # wipe the entire array! - now threadsafe with lock
                self._arr[...] = values[-self._capacity :]
                self._right_index = self._capacity
                self._left_index = 0
                self.resized.emit(len(self))
                return

            was_full = len(self) == self._capacity
            ri = self._right_index % self._capacity
            sl1 = np.s_[ri : min(ri + lv, self._capacity)]
            sl2 = np.s_[: max(ri + lv - self._capacity, 0)]
            self._arr[sl1] = values[: sl1.stop - sl1.start]
            self._arr[sl2] = values[sl1.stop - sl1.start :]
            self._right_index += lv

            self._left_index = max(self._left_index, self._right_index - self._capacity)
            self._fix_indices()
            if not was_full:
                self.resized.emit(len(self))

    def clear(self) -> None:
        """Clear all elements from the buffer.

        In practice, it resets the left and right indices,
        invalidating all existing data.
        """
        with self._lock:
            self._left_index = 0
            self._right_index = 0
            self.resized.emit(0)

    def extendleft(self, values: npt.ArrayLike) -> None:
        """Prepend the buffer with the given values."""
        with self._lock:
            values = np.asarray(values)
            lv = len(values)
            if len(self) + lv > self._capacity:
                if not self._allow_overwrite:
                    raise IndexError(
                        "Extending a RingBuffer such that it would overflow, "
                        "with overwrite disabled"
                    )
                elif not len(self):
                    return
            if lv >= self._capacity:
                # wipe the entire array! - now threadsafe with lock
                self._arr[...] = values[: self._capacity]
                self._right_index = self._capacity
                self._left_index = 0
                self.resized.emit(len(self))
                return

            was_full = len(self) == self._capacity
            self._left_index -= lv
            self._fix_indices()
            li = self._left_index
            sl1 = np.s_[li : min(li + lv, self._capacity)]
            sl2 = np.s_[: max(li + lv - self._capacity, 0)]
            self._arr[sl1] = values[: sl1.stop - sl1.start]
            self._arr[sl2] = values[sl1.stop - sl1.start :]

            self._right_index = min(
                self._right_index, self._left_index + self._capacity
            )
            if not was_full:
                self.resized.emit(len(self))

    # numpy compatibility
    def __array__(  # noqa: D105
        self, dtype: npt.DTypeLike | None = None, copy: bool | None = None
    ) -> npt.NDArray[Any]:
        if copy is False:
            warnings.warn(
                "`copy=False` isn't supported. A copy is always created.",
                RuntimeWarning,
                stacklevel=2,
            )
        with self._lock:
            return np.asarray(self._unwrap(), dtype=dtype)

    # implement Sequence methods
    def __len__(self) -> int:
        """Return the number of valid elements in the buffer."""
        return self._right_index - self._left_index

    @overload  # type: ignore [override]
    def __getitem__(self, key: SupportsIndex) -> Any: ...
    @overload
    def __getitem__(self, key: Any, /) -> npt.NDArray[Any]: ...
    def __getitem__(self, key: Any) -> npt.NDArray[Any] | Any:
        """Index into the buffer.

        This supports both simple and fancy indexing.
        """
        with self._lock:
            # handle simple (b[1]) and basic (b[np.array([1, 2, 3])]) fancy indexing quickly
            if not isinstance(key, tuple):
                item_arr = np.asarray(key)
                if issubclass(item_arr.dtype.type, np.integer):
                    # Map negative indices to positive ones
                    item_arr = np.where(item_arr < 0, item_arr + len(self), item_arr)
                    # Map indices to the range of the buffer
                    item_arr = (item_arr + self._left_index) % self._capacity
                    return self._arr[item_arr].copy()

            # for everything else, get it right at the expense of efficiency
            return self._unwrap()[key]

    def __iter__(self) -> Iterator[npt.NDArray[Any]]:  # noqa: D105
        # this is comparable in speed to using itertools.chain
        with self._lock:
            return iter(self._unwrap())

    def __repr__(self) -> str:
        """Return a string representation of the buffer."""
        with self._lock:
            return f"<{self.__class__.__name__} of {np.asarray(self)!r}>"

    def _unwrap(self) -> npt.NDArray[Any]:
        """Copy the data from this buffer into unwrapped form."""
        return np.concatenate(
            (
                self._arr[self._left_index : min(self._right_index, self._capacity)],
                self._arr[: max(self._right_index - self._capacity, 0)],
            )
        )

    def _fix_indices(self) -> None:
        """Enforce our invariant that 0 <= self._left_index < self._capacity."""
        if self._left_index >= self._capacity:
            self._left_index -= self._capacity
            self._right_index -= self._capacity
        elif self._left_index < 0:
            self._left_index += self._capacity
            self._right_index += self._capacity
