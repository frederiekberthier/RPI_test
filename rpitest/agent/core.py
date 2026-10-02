from __future__ import annotations

import ipaddress
import re
import threading
from collections.abc import Callable

from ..gpio.ports import GpioPort
from ..system.ops import OpsError, SystemOps

_BLOCK = re.compile(r"^sd[a-z]{1,2}$")
_MAC = re.compile(r"^(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")


def _ipv4(host) -> str:
    try:
        return str(ipaddress.IPv4Address(host))
    except ValueError as exc:
        raise ValueError(f"geen geldig IPv4-adres: {host!r}") from exc


def _int_between(value, low: int, high: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} moet een geheel getal tussen {low} en {high} zijn")
    return value


def _ssid(value) -> str:
    if not isinstance(value, str) or not 1 <= len(value.encode()) <= 32 or not value.isprintable():
        raise ValueError("ongeldige SSID")
    return value


def _password(value) -> str:
    if not isinstance(value, str) or not 8 <= len(value) <= 63 or not value.isascii() or not value.isprintable():
        raise ValueError("ongeldig wachtwoord (8 tot 63 afdrukbare ASCII-tekens)")
    return value


class Agent:
    """Draait op de DUT. Voert opdrachten van de tester uit via een vaste lijst methodes met
    gevalideerde parameters; er is bewust geen manier om willekeurige commando's uit te voeren."""

    def __init__(self, gpio: GpioPort, info_fn: Callable[[], dict], ops: SystemOps | None = None):
        self._gpio = gpio
        self._info_fn = info_fn
        self._ops = ops
        self._lock = threading.Lock()
        self._methods = {
            "ping": self.ping,
            "info": self.info,
            "gpio_set_input": self.gpio_set_input,
            "gpio_drive": self.gpio_drive,
            "gpio_read": self.gpio_read,
            "net_iface_info": self.net_iface_info,
            "net_ping": self.net_ping,
            "iperf3_server_start": self.iperf3_server_start,
            "iperf3_server_stop": self.iperf3_server_stop,
            "wifi_info": self.wifi_info,
            "wifi_scan": self.wifi_scan,
            "wifi_connect": self.wifi_connect,
            "wifi_link": self.wifi_link,
            "wifi_forget": self.wifi_forget,
            "bt_info": self.bt_info,
            "bt_scan": self.bt_scan,
            "bt_discoverable": self.bt_discoverable,
            "usb_scan": self.usb_scan,
            "usb_storage_test": self.usb_storage_test,
            "usb_uptime": self.usb_uptime,
            "usb_kernel_events": self.usb_kernel_events,
            "power_sample": self.power_sample,
            "stress_start": self.stress_start,
            "stress_poll": self.stress_poll,
            "stress_result": self.stress_result,
            "stress_stop": self.stress_stop,
        }

    def dispatch(self, method: str, params: dict):
        fn = self._methods.get(method)
        if fn is None:
            raise KeyError(f"onbekende methode: {method}")
        with self._lock:
            try:
                return fn(**params)
            except OpsError as exc:  # laat de tester het verschil zien tussen "faalt" en "kan niet"
                raise RuntimeError(f"OpsError: {exc}") from exc

    @property
    def ops(self) -> SystemOps:
        if self._ops is None:
            raise RuntimeError("deze agent heeft geen systeem-backend")
        return self._ops

    def ping(self) -> str:
        return "pong"

    def info(self) -> dict:
        return self._info_fn()

    # --- GPIO ---
    def gpio_set_input(self, pins: list[int], pull: str) -> None:
        self._gpio.set_input(pins, pull)

    def gpio_drive(self, pin: int, value: int) -> None:
        self._gpio.drive(pin, value)

    def gpio_read(self, pins: list[int]) -> dict[str, int]:
        # JSON kent alleen string-sleutels
        return {str(p): v for p, v in self._gpio.read(pins).items()}

    # --- wired netwerk ---
    def net_iface_info(self) -> dict:
        return self.ops.net_iface_info()

    def net_ping(self, host: str, count: int) -> dict:
        return self.ops.ping(_ipv4(host), _int_between(count, 1, 100, "count"))

    def iperf3_server_start(self) -> None:
        self.ops.iperf3_server_start()

    def iperf3_server_stop(self) -> None:
        self.ops.iperf3_server_stop()

    # --- wifi ---
    def wifi_info(self) -> dict:
        return self.ops.wifi_info()

    def wifi_scan(self) -> list[dict]:
        return self.ops.wifi_scan()

    def wifi_connect(self, ssid: str, password: str) -> dict:
        return self.ops.wifi_connect(_ssid(ssid), _password(password))

    def wifi_link(self) -> dict:
        return self.ops.wifi_link()

    def wifi_forget(self) -> None:
        self.ops.wifi_forget()

    # --- bluetooth ---
    def bt_info(self) -> dict:
        return self.ops.bt_info()

    def bt_scan(self, seconds: int, forget_mac: str | None = None) -> list[dict]:
        if forget_mac is not None and not _MAC.match(forget_mac):
            raise ValueError("ongeldig MAC-adres")
        return self.ops.bt_scan(_int_between(seconds, 1, 60, "seconds"), forget_mac)

    def bt_discoverable(self, enabled: bool) -> None:
        if not isinstance(enabled, bool):
            raise ValueError("enabled moet true of false zijn")
        self.ops.bt_discoverable(enabled)

    # --- usb ---
    def usb_scan(self) -> list[dict]:
        return self.ops.usb_scan()

    def usb_storage_test(self, block: str, size_mb: int) -> dict:
        if not isinstance(block, str) or not _BLOCK.match(block):
            raise ValueError("ongeldig blokapparaat")
        return self.ops.usb_storage_test(block, _int_between(size_mb, 1, 256, "size_mb"))

    def usb_uptime(self) -> float:
        return self.ops.usb_uptime()

    def usb_kernel_events(self) -> list[dict]:
        return self.ops.usb_kernel_events()

    # --- voeding, temperatuur en belasting ---
    def power_sample(self) -> dict:
        return self.ops.power_sample()

    def stress_start(self, seconds: int, ram_mb: int) -> None:
        self.ops.stress_start(_int_between(seconds, 5, 300, "seconds"), _int_between(ram_mb, 16, 2048, "ram_mb"))

    def stress_poll(self) -> dict:
        return self.ops.stress_poll()

    def stress_result(self) -> dict:
        return self.ops.stress_result()

    def stress_stop(self) -> None:
        self.ops.stress_stop()
