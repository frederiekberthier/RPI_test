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


def _number(slot: dict, key: str, where: str) -> None:
    value = slot.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"{where}: '{key}' ontbreekt of is geen getal")


def validate_usb_slots(slots) -> list[dict]:
    """Controleert een lijst USB-slots (uit --usb-fixture); gooit ValueError met een duidelijke melding."""
    if not isinstance(slots, list) or not slots:
        raise ValueError("verwacht een niet-lege lijst van slots")
    seen: set[str] = set()
    for number, slot in enumerate(slots, 1):
        where = f"slot {number}"
        if not isinstance(slot, dict):
            raise ValueError(f"{where}: verwacht een object met label, min_speed_mbit en min_read_mb_s")
        label = slot.get("label")
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"{where}: 'label' ontbreekt")
        if label in seen:
            raise ValueError(f"{where}: label {label!r} komt twee keer voor")
        seen.add(label)
        where = f"slot {number} ({label})"
        _number(slot, "min_speed_mbit", where)
        _number(slot, "min_read_mb_s", where)
        if "name" in slot and not isinstance(slot["name"], str):
            raise ValueError(f"{where}: 'name' moet tekst zijn")
    return slots


def load_usb_slots(path: Path | None) -> list[dict] | None:
    """Leest en controleert het fixturebestand; ValueError met een bruikbare melding bij elk probleem."""
    if not path:
        return None
    try:
        slots = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"USB-fixturebestand {path} niet te lezen: {exc}") from exc
    except ValueError as exc:
        raise ValueError(f"USB-fixturebestand {path} is geen geldige JSON: {exc}") from exc
    try:
        return validate_usb_slots(slots)
    except ValueError as exc:
        raise ValueError(f"USB-fixturebestand {path}: {exc}") from exc


def split_faults(faults: list[str]) -> tuple[list[str], MockWiring]:
    """Verdeelt --fault-opgaven in systeemfouten en een bedrading met GPIO-fouten; ValueError bij een foute opgave."""
    wiring = MockWiring()
    sys_faults = []
    for spec in faults:  # bv. stuck_low:C:5  stuck_high:S:9  bridge:C:5:6  open:7  eth_100  no_wifi
        kind, *args = spec.split(":")
        if kind in sysmock.KNOWN_FAULTS:
            if args:
                raise ValueError(f"--fault {spec}: fout {kind!r} heeft geen argumenten")
            sys_faults.append(kind)
        else:
            try:
                wiring.add_fault(kind, *args)
            except ValueError as exc:
                raise ValueError(f"--fault {spec}: {exc}") from exc
    return sys_faults, wiring


def mock_context(faults: list[str], usb_slots: list[dict] | None = None) -> tuple[Context, Closer]:
    sys_faults, wiring = split_faults(faults)
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
    from .sysinfo import pi_info
    from .system.linux import LinuxOps

    port = GpiodPort(gpio_chip)
    ops = LinuxOps()
    client = RpcClient(client_url)
    ctx = Context(port, RemoteGpioPort(client), client, pi_info(), ops, usb_slots)

    def close() -> None:
        ops.close()  # stopt belasting, iperf3, bluetooth-zichtbaarheid, hotspot en wifi-profiel
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
