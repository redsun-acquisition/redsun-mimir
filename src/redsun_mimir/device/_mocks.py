from __future__ import annotations

from typing import TYPE_CHECKING, Final

from ophyd_async.core import (
    AsyncStatus,
    SignalRW,
    SoftSignalBackend,
    StandardReadable,
    StandardReadableFormat,
    soft_signal_r_and_setter,
    soft_signal_rw,
)
from ophyd_async.core._signal_backend import SignalDatatypeT
from redsun.log import Loggable

if TYPE_CHECKING:
    from event_model.documents import DataKey, Limits
    from ophyd_async.core._soft_signal_backend import Getter, Setter

#: Seconds a signal waits for a value to settle.
SIGNAL_TIMEOUT: Final = 5.0


class BoundedSoftSignalBackend(SoftSignalBackend[SignalDatatypeT]):
    """A ``SoftSignalBackend`` reporting control limits in its ``DataKey``.

    The soft backend's ``make_metadata`` covers only units and precision,
    and the light view sizes its slider from ``limits.control``. *getter*,
    *setter* and *poll_period* are forwarded, so a bounded signal can be
    hardware-backed like any other soft signal.
    """

    def __init__(
        self,
        low: float,
        high: float,
        units: str | None = None,
        initial_value: SignalDatatypeT | None = None,
        *,
        datatype: type[SignalDatatypeT] = float,  # type: ignore[assignment]
        getter: Getter[SignalDatatypeT] | None = None,
        setter: Setter[SignalDatatypeT] | None = None,
        poll_period: float | None = None,
    ) -> None:
        super().__init__(
            datatype,
            initial_value=initial_value,
            units=units,
            getter=getter,
            setter=setter,
            poll_period=poll_period,
        )
        self._low: float = low
        self._high: float = high

    async def get_datakey(self, source: str) -> DataKey:
        """Return the data key, with control limits."""
        dk = await super().get_datakey(source)
        # inject control limits into the DataKey
        limits: Limits = {"control": {"low": self._low, "high": self._high}}
        dk["limits"] = limits
        return dk


def bounded_soft_signal_rw(
    low: float,
    high: float,
    units: str | None = None,
    initial_value: SignalDatatypeT | None = None,
    *,
    datatype: type[SignalDatatypeT] = float,  # type: ignore[assignment]
    name: str = "bounded_signal",
    getter: Getter[SignalDatatypeT] | None = None,
    setter: Setter[SignalDatatypeT] | None = None,
    poll_period: float | None = None,
) -> SignalRW[SignalDatatypeT]:
    """Return a soft signal with control limits in its ``DataKey``.

    *getter* and *setter* back it with a hardware call; without them the
    value lives in memory.
    """
    backend = BoundedSoftSignalBackend(
        low,
        high,
        units,
        initial_value,
        datatype=datatype,
        getter=getter,
        setter=setter,
        poll_period=poll_period,
    )
    return SignalRW(backend, name=name, timeout=SIGNAL_TIMEOUT)


class MockLightDevice(StandardReadable, Loggable):
    """Mock light source for simulation and tests.

    Parameters
    ----------
    wavelength :
        In nanometres.
    binary :
        Mark the source as on/off only.
    range :
        Bounds of ``intensity`` in mW, ignored when *binary*.
    """

    def __init__(
        self,
        name: str,
        *,
        wavelength: int = 0,
        binary: bool = False,
        range: tuple[float, float] = (0.0, 200.0),
    ) -> None:
        if len(range) != 2:
            raise ValueError("Range must be a list of two floats [low, high]")
        if range[0] >= range[1]:
            raise ValueError("Range low value must be less than high value")

        with self.add_children_as_readables():
            self.intensity = bounded_soft_signal_rw(
                range[0], range[1], units="mW", initial_value=0.0
            )
            self.enabled = soft_signal_rw(bool, initial_value=False)

        with self.add_children_as_readables(StandardReadableFormat.CONFIG_SIGNAL):
            self.wavelength, _ = soft_signal_r_and_setter(int, initial_value=wavelength)
            self.binary, _ = soft_signal_r_and_setter(bool, initial_value=binary)

        super().__init__(name)

    @AsyncStatus.wrap
    async def trigger(self) -> None:
        """Toggle the light source on or off."""
        current = await self.enabled.get_value()
        await self.enabled.set(not current)
        self.logger.debug(
            f"{'Enabled' if not current else 'Disabled'} light source {self.name}"
        )
