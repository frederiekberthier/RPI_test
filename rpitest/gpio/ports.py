from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

# BCM 2..27 = de 26 vrije GPIO's op de 40-pins header.
# BCM 0 en 1 zijn gereserveerd voor de HAT-ID-EEPROM en worden niet getest.
PINS: tuple[int, ...] = tuple(range(2, 28))

# GPIO2/3 hebben op de Pi een vaste pull-up van 1,8 kOhm naar 3V3 (I2C).
EXTERNAL_PULLUP: frozenset[int] = frozenset({2, 3})

# BCM-nummer -> fysieke pin op de 40-pins header (voor in rapporten en de bedradingshandleiding).
HEADER_PIN: dict[int, int] = {
    2: 3, 3: 5, 4: 7, 5: 29, 6: 31, 7: 26, 8: 24, 9: 21, 10: 19, 11: 23, 12: 32, 13: 33,
    14: 8, 15: 10, 16: 36, 17: 11, 18: 12, 19: 35, 20: 38, 21: 40, 22: 15, 23: 16,
    24: 18, 25: 22, 26: 37, 27: 13,
}
# Deze headerpinnen mogen NOOIT tussen TEST-SERVER en TEST-CLIENT verbonden worden (voeding).
POWER_HEADER_PINS: frozenset[int] = frozenset({1, 2, 4, 17})
GND_HEADER_PINS: tuple[int, ...] = (6, 9, 14, 20, 25, 30, 34, 39)


def label(pin: int) -> str:
    return f"GPIO{pin} (pin {HEADER_PIN[pin]})"


class Pull:
    NONE = "none"
    UP = "up"
    DOWN = "down"
    ALL = (NONE, UP, DOWN)


class GpioPort(ABC):
    """GPIO-kant van een Pi. Zowel de TEST-SERVER als de TEST-CLIENT (via de agent) implementeren dit."""

    @abstractmethod
    def set_input(self, pins: Iterable[int], pull: str) -> None:
        """Zet pinnen als input met de gevraagde pull (Pull.*)."""

    @abstractmethod
    def drive(self, pin: int, value: int) -> None:
        """Zet een pin als output met waarde 0 of 1."""

    @abstractmethod
    def read(self, pins: Iterable[int]) -> dict[int, int]:
        """Lees het niveau van de pinnen."""
