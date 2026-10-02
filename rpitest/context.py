from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .gpio.ports import GpioPort


class Client(Protocol):
    def call(self, method: str, **params): ...


@dataclass
class Context:
    """Alles wat een check nodig heeft om tester en DUT aan te sturen."""

    tester_gpio: GpioPort  # lokale GPIO van de testpi
    dut_gpio: GpioPort  # GPIO van de DUT, via de agent
    dut: Client  # algemene agent-aanroepen (info, later usb/wifi/...)
    tester_info: dict
