"""Presenter for filter wheel control."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from dependency_injector import providers
from redsun.aio import run_coro
from redsun.device.protocols import HasAsyncShutdown
from redsun.log import Loggable
from redsun.presenter import Presenter
from redsun.utils import find_signals

from redsun_mimir.device.mmcore._stated import MMBaseStatedDevice

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    from bluesky.protocols import Descriptor, Reading
    from ophyd_async.core import Device
    from redsun.virtual import VirtualContainer


class FilterWheelPresenter(Presenter, Loggable):
    """Presenter for filter wheel position control.

    Discovers stated devices and exposes their labels and current
    positions to the ``FilterWheelView``.

    Parameters
    ----------
    name : str
        Identity key of the presenter.
    devices : Mapping[str, Device]
        Mapping of device names to device instances.
    timeout : float | None
        Status wait timeout in seconds (default ``2.0``).
    """

    def __init__(
        self,
        name: str,
        devices: Mapping[str, Device],
        /,
        timeout: float | None = None,
    ) -> None:
        super().__init__(name, devices)
        self._timeout = timeout or 2.0
        self._wheels: dict[str, MMBaseStatedDevice] = {
            name: device
            for name, device in devices.items()
            if isinstance(device, MMBaseStatedDevice)
        }
        if self._wheels:
            names = ", ".join(d.name for d in self._wheels.values())
            self.logger.debug("Found filter wheels: %s", names)
        else:
            self.logger.warning("No filter wheel device found.")

    def device_readings(self) -> dict[str, Reading[Any]]:
        result: dict[str, Reading[Any]] = {}
        for name, wheel in self._wheels.items():
            labels = wheel.labels
            result[f"{name}-labels"] = {
                "value": json.dumps({str(k): v for k, v in labels.items()}),
                "timestamp": 0.0,
            }
        return result

    def device_description(self) -> dict[str, Descriptor]:
        result: dict[str, Descriptor] = {}
        for name in self._wheels:
            result[f"{name}-labels"] = {
                "source": "settings",
                "dtype": "string",
                "shape": [],
            }
        return result

    def register_providers(self, container: VirtualContainer) -> None:
        container.fw_readings = providers.Object(self.device_readings())
        container.fw_description = providers.Object(self.device_description())
        container.register_signals(self)

    def inject_dependencies(self, container: VirtualContainer) -> None:
        sigs = find_signals(container, ["sigFilterWheelChange"])
        if "sigFilterWheelChange" in sigs:
            sigs["sigFilterWheelChange"].connect(
                lambda name, label: run_coro(self.set_label(name, label))
            )

    async def set_label(self, name: str, label: str) -> None:
        wheel = self._wheels[name]
        await wheel.set_label(label)
        self.logger.info("Filter wheel %s -> %s", name, label)

    def shutdown(self) -> None:
        for wheel in self._wheels.values():
            if isinstance(wheel, HasAsyncShutdown):
                run_coro(wheel.shutdown())
