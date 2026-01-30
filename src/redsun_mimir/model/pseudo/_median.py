from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

import numpy as np
from sunflare.engine import Status

from redsun_mimir.protocols import PseudoModelProtocol

if TYPE_CHECKING:
    from typing import Any, TypedDict

    import numpy.typing as npt
    from bluesky.protocols import Descriptor, Reading
    from sunflare.config import ModelInfo

    class PrepareKwargs(TypedDict):
        """Configuration parameters for preparing the pseudo-model."""

        num_steps: int
        """Number of steps that will be stashed before triggering."""

        data_keys: list[dict[str, dict[str, Descriptor]]]
        """List of descriptors involved in the stashing process."""


class MedianPseudoModel(PseudoModelProtocol):
    """Pseudo-model that computes the median of stashed readings.

    Readings are stashed per device and the median computed
    along the time axis when `trigger()` is called.
    """

    def __init__(self, name: str, model_info: ModelInfo) -> None:
        self._name = name
        self._model_info = model_info
        self._stashed_readings: deque[dict[str, Reading[Any]]] = deque()
        self._median_datakey = f"PSEUDO:{self._name}/median"
        self._owners_datakey = f"PSEUDO:{self._name}/owners"
        self._medians: dict[str, npt.NDArray[np.float64]] = {}
        self._num_steps: int = 0
        self._descriptors: dict[str, dict[str, Descriptor]] = {}
        self._ready = False

    def describe_configuration(self) -> dict[str, Descriptor]:
        """Return a descriptor of the configuration data.

        There are no configuration parameters for this pseudo-model,
        so an empty dictionary is returned.
        """
        return {}

    def describe(self) -> dict[str, Descriptor]:
        """Return a descriptor of the output data.

        Returns
        -------
        dict[str, Descriptor]
            A dictionary mapping data keys to their descriptors.

        Notes
        -----
        The pseudo-model does not know in advance the
        number of detectors.

        It can only know that it will output a 3D array:

        - array[0]: detectors (unknown number)
        - array[1]: y-axis
        - array[2]: x-axis

        The final calculation will produce
        a float64 array.
        """
        return {
            self._median_datakey: {
                "source": "pseudo-model",
                "dtype": "array",
                "shape": [None, None, None],
                "dtype_numpy": "float64",
            }
        }

    def prepare(self, value: PrepareKwargs) -> Status:
        """Prepare the pseudo-model for triggering.

        Provide in advance the number of steps that will be stashed
        before triggering, to optimize memory allocation.
        """
        s = Status()
        self._num_steps = value["num_steps"]
        data_keys_list = value["data_keys"]

        # Pre-allocate arrays for array-type data keys
        self._medians = {}

        for descriptors_map in data_keys_list:
            for device_name, descriptors in descriptors_map.items():
                for data_key, descriptor in descriptors.items():
                    # Filter for array dtype with valid shape
                    if descriptor.get("dtype") != "array":
                        continue

                    shape = descriptor.get("shape")
                    if shape is None or len(shape) not in (2, 3):
                        continue

                    # Extract spatial dimensions (last 2 elements)
                    y, x = tuple(shape[-2:])
                    if not y or not x:
                        continue

                    full_shape = (self._num_steps, y, x)
                    key = f"{device_name}/{data_key}"
                    self._medians[key] = np.zeros(full_shape, dtype=np.float64)

        s.set_finished()
        return s

    def read(self) -> dict[str, Reading[Any]]:
        return {}

    def trigger(self) -> Status:
        s = Status()
        for step_idx, stashed in enumerate(self._stashed_readings):
            for key, median_array in self._medians.items():
                reading = stashed.get(key)
                if reading is None:
                    continue

                data = reading.get("value")
                if not isinstance(data, np.ndarray):
                    continue

                median_array[step_idx, :, :] = data.astype(np.float64)
        # Compute median across time axis (axis=0)
        # median_results = {
        #     self._median_datakey: np.median(median_array, axis=0)
        #     for median_array in self._medians.values()
        # }
        return s

    def stash(self, value: dict[str, Reading[Any]]) -> None:
        self._stashed_readings.append(value)

    def clear(self) -> None:
        self._stashed_readings.clear()

    @property
    def name(self) -> str:
        return self._name

    @property
    def parent(self) -> None:
        return None

    @property
    def model_info(self) -> ModelInfo:
        return self._model_info
