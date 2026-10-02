from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

# BCM 2..27 = de 26 vrije GPIO's op de 40-pins header.
# BCM 0 en 1 zijn gereserveerd voor de HAT-ID-EEPROM en worden niet getest.
PINS: tuple[int, ...] = tuple(range(2, 28))

# GPIO2/3 hebben op de Pi een vaste pull-up van 1,8 kOhm naar 3V3 (I2C).
EXTERNAL_PULLUP: frozenset[int] = frozenset({2, 3})


class Pull:
    NONE = "none"
    UP = "up"
    DOWN = "down"
    ALL = (NONE, UP, DOWN)


class GpioPort(ABC):
    """GPIO-kant van een Pi. Zowel de testpi als de DUT (via de agent) implementeren dit."""

    @abstractmethod
    def set_input(self, pins: Iterable[int], pull: str) -> None:
        """Zet pinnen als input met de gevraagde pull (Pull.*)."""

    @abstractmethod
    def drive(self, pin: int, value: int) -> None:
        """Zet een pin als output met waarde 0 of 1."""

    @abstractmethod
    def read(self, pins: Iterable[int]) -> dict[int, int]:
        """Lees het niveau van de pinnen."""
