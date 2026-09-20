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
    """SoftSignalBackend that exposes control limits in its DataKey.

    ``limits`` is the one piece of metadata ophyd-async's soft backend cannot
    express (``make_metadata`` covers only units and precision), so this
    subclass stays even for signals that are otherwise plain callables - the
    light view sizes its slider from ``limits.control``.

    ``getter``/``setter``/``poll_period`` are forwarded untouched, so a
    bounded signal can be hardware-backed like any other soft signal.
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
        """Get the data key for this signal, including control limits."""
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
    """Create a bounded soft signal with control limits in its DataKey.

    Pass *getter*/*setter* to back the signal with a hardware call; leave
    them out for a purely in-memory bounded value.
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
    """Mock light source for simulation and testing purposes.

    Parameters
    ----------
    name : str
        Device name.
    wavelength : int, optional
        Wavelength of the light source in nanometers. Defaults to ``0``.
    binary : bool, optional
        Mark the source as on/off only. Defaults to ``False``.
    range : tuple[float, float], optional
        Bounds of ``intensity`` in mW. Ignored when *binary*.
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
        """Toggle the activation status of the light source."""
        current = await self.enabled.get_value()
        await self.enabled.set(not current)
        self.logger.debug(
            f"{'Enabled' if not current else 'Disabled'} light source {self.name}"
        )
