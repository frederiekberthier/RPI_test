from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .gpio.ports import GpioPort
from .system.ops import SystemOps


class Client(Protocol):
    def call(self, method: str, _timeout: float | None = None, **params): ...


@dataclass
class Context:
    """Alles wat een check nodig heeft om de TEST-SERVER en de TEST-CLIENT aan te sturen."""

    server_gpio: GpioPort  # lokale GPIO van de TEST-SERVER
    client_gpio: GpioPort  # GPIO van de TEST-CLIENT, via de agent
    client: Client  # algemene agent-aanroepen (info, netwerk, wifi, bluetooth, ...)
    server_info: dict
    server_ops: SystemOps | None = None  # netwerk/wifi/bluetooth aan de kant van de TEST-SERVER
    usb_slots: list[dict] | None = None  # None: config.USB_SLOTS
