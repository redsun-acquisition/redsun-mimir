from typing import Protocol, runtime_checkable
from bluesky.protocols import Location
from sunflare.model import ModelProtocol
from sunflare.engine import Status


@runtime_checkable
class MotorProtocol(ModelProtocol, Protocol):
    """Protocol for motor models."""

    def set(self, value: float) -> Status:
        """Move the motor to a given position."""
        ...

    def locate(self) -> Location[float]:
        """Return the current motor position."""
        ...
