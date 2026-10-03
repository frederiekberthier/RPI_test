"""Bouwt de Context (TEST-SERVER + TEST-CLIENT) voor de opdrachtregel en voor het scherm."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from . import config
from .agent.client import LocalClient, RemoteGpioPort, RpcClient, RpcError
from .agent.core import Agent
from .context import Context
from .gpio.mock import CLIENT, SERVER, MockWiring
from .system import mock as sysmock

MOCK_CLIENT_INFO = {"model": "Raspberry Pi 5 Model B Rev 1.0 (mock)", "ram_mb": 8192, "serial": "MOCK0001"}
Closer = Callable[[], None]
ContextFactory = Callable[[], "tuple[Context, Closer]"]


def default_client_url() -> str:
    return f"http://{config.CLIENT_IP}:{config.AGENT_PORT}"


def load_usb_slots(path: Path | None) -> list[dict] | None:
    return json.loads(path.read_text(encoding="utf-8")) if path else None


def mock_context(faults: list[str], usb_slots: list[dict] | None = None) -> tuple[Context, Closer]:
    wiring = MockWiring()
    sys_faults = []
    for spec in faults:  # bv. stuck_low:C:5  stuck_high:S:9  bridge:C:5:6  open:7  eth_100  no_wifi
        kind, *args = spec.split(":")
        if kind in sysmock.KNOWN_FAULTS:
            sys_faults.append(kind)
        else:
            wiring.add_fault(kind, *args)
    env = sysmock.MockEnv(sys_faults)
    client = LocalClient(Agent(wiring.port(CLIENT), lambda: MOCK_CLIENT_INFO, env.ops(sysmock.CLIENT)))
    ctx = Context(wiring.port(SERVER), RemoteGpioPort(client), client, {"model": "Raspberry Pi 5 (mock TEST-SERVER)"},
                  env.ops(sysmock.SERVER), usb_slots)
    return ctx, lambda: None


def real_context(client_url: str, gpio_chip: str | None = None,
                 usb_slots: list[dict] | None = None) -> tuple[Context, Closer]:
    """Opent de GPIO van de TEST-SERVER. Gooit RuntimeError met een bruikbare melding als dat niet lukt."""
    # pas hier importeren: vereist gpiod en dus een echte Pi
    from .gpio.real import GpiodPort
    from .system.linux import LinuxOps
    from .sysinfo import pi_info

    port = GpiodPort(gpio_chip)
    ops = LinuxOps()
    client = RpcClient(client_url)
    ctx = Context(port, RemoteGpioPort(client), client, pi_info(), ops, usb_slots)

    def close() -> None:
        ops.close()  # stopt hotspot-resten, iperf3, zichtbaarheid
        port.close()

    return ctx, close


def mock_probe() -> dict | None:
    return dict(MOCK_CLIENT_INFO)


def real_probe(client_url: str) -> Callable[[], dict | None]:
    """Snelle controle of de agent op de TEST-CLIENT bereikbaar is; geeft de gegevens van de TEST-CLIENT of None."""
    client = RpcClient(client_url, timeout=1.5)

    def probe() -> dict | None:
        try:
            client.call("ping")
            return client.call("info")
        except RpcError:
            return None

    return probe
