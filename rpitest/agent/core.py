from __future__ import annotations

import threading
from collections.abc import Callable

from ..gpio.ports import GpioPort


class Agent:
    """Draait op de DUT. Voert opdrachten van de tester uit via een vaste lijst methodes."""

    def __init__(self, gpio: GpioPort, info_fn: Callable[[], dict]):
        self._gpio = gpio
        self._info_fn = info_fn
        self._lock = threading.Lock()
        self._methods = {
            "ping": self.ping,
            "info": self.info,
            "gpio_set_input": self.gpio_set_input,
            "gpio_drive": self.gpio_drive,
            "gpio_read": self.gpio_read,
        }

    def dispatch(self, method: str, params: dict):
        fn = self._methods.get(method)
        if fn is None:
            raise KeyError(f"onbekende methode: {method}")
        with self._lock:
            return fn(**params)

    def ping(self) -> str:
        return "pong"

    def info(self) -> dict:
        return self._info_fn()

    def gpio_set_input(self, pins: list[int], pull: str) -> None:
        self._gpio.set_input(pins, pull)

    def gpio_drive(self, pin: int, value: int) -> None:
        self._gpio.drive(pin, value)

    def gpio_read(self, pins: list[int]) -> dict[str, int]:
        # JSON kent alleen string-sleutels
        return {str(p): v for p, v in self._gpio.read(pins).items()}
