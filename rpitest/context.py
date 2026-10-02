from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .gpio.ports import GpioPort
from .system.ops import SystemOps


class Client(Protocol):
    def call(self, method: str, _timeout: float | None = None, **params): ...


@dataclass
class Context:
    """Alles wat een check nodig heeft om tester en DUT aan te sturen."""

    tester_gpio: GpioPort  # lokale GPIO van de testpi
    dut_gpio: GpioPort  # GPIO van de DUT, via de agent
    dut: Client  # algemene agent-aanroepen (info, netwerk, wifi, bluetooth, ...)
    tester_info: dict
    tester_ops: SystemOps | None = None  # netwerk/wifi/bluetooth aan de kant van de testpi
