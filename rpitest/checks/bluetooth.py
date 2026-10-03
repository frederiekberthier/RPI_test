"""Bluetooth van de TEST-CLIENT: ontvangen (TEST-CLIENT ziet de TEST-SERVER) en zenden (TEST-SERVER ziet de TEST-CLIENT).

Bluetooth en wifi delen op de Pi dezelfde chip; deze check draait daarom na de wifi-check."""

from __future__ import annotations

from .. import config
from ..agent.client import RpcError
from ..context import Context
from ..models import CheckResult, Status
from ..system.ops import OpsError

_TOOL_ERRORS = RpcError  # een fout van de TEST-CLIENT; een OpsError komt van de TEST-SERVER zelf


def _server_problem(name: str, exc: Exception) -> CheckResult:
    return CheckResult(name, Status.SKIP, f"overgeslagen: probleem aan de TEST-SERVER, niet aan de TEST-CLIENT: {exc}")


def run(ctx: Context) -> list[CheckResult]:
    if ctx.server_ops is None:
        return [CheckResult("bluetooth", Status.SKIP, "overgeslagen: TEST-SERVER heeft geen systeem-backend")]
    try:
        server = ctx.server_ops.bt_info()
        if not server["present"]:
            return [CheckResult("bluetooth", Status.SKIP, "overgeslagen: de TEST-SERVER heeft geen bluetooth-controller")]
        client = ctx.client.call("bt_info")
    except OpsError as exc:
        return [_server_problem("bt.controller", exc)]
    except _TOOL_ERRORS as exc:
        return [CheckResult("bt.controller", Status.FAIL, f"bluetooth-gegevens niet op te halen: {exc}")]

    controller = check_controller(client)
    if controller.status is Status.FAIL:
        return [controller,
                CheckResult("bt.receive", Status.SKIP, "overgeslagen: geen werkende controller"),
                CheckResult("bt.transmit", Status.SKIP, "overgeslagen: geen werkende controller")]
    return [controller, check_receive(ctx, server["address"]), check_transmit(ctx, client["address"])]


def check_controller(info: dict) -> CheckResult:
    if not info["present"]:
        return CheckResult("bt.controller", Status.FAIL, "geen bluetooth-controller op de TEST-CLIENT", info)
    if not info["powered"]:
        return CheckResult("bt.controller", Status.FAIL, "bluetooth-controller kan niet ingeschakeld worden", info)
    return CheckResult("bt.controller", Status.PASS, f"controller {info['address']} actief", info)


def _verdict(name: str, found: list[dict], address: str, ok_text: str, fail_text: str) -> CheckResult:
    match = next((d for d in found if d["address"].upper() == address.upper()), None)
    details = {"expected": address, "devices_seen": found}
    if match is None:
        return CheckResult(name, Status.FAIL, fail_text, details)
    rssi = match.get("rssi")
    return CheckResult(name, Status.PASS, f"{ok_text} (RSSI {rssi} dBm)" if rssi is not None else ok_text, details)


def check_receive(ctx: Context, server_address: str) -> CheckResult:
    """De TEST-SERVER is zichtbaar; de TEST-CLIENT moet hem zien."""
    secs = config.BT_SCAN_SECONDS
    try:
        ctx.server_ops.bt_discoverable(True)
        try:
            found = ctx.client.call("bt_scan", seconds=secs, forget_mac=server_address, _timeout=secs + 25)
        finally:
            ctx.server_ops.bt_discoverable(False)
    except OpsError as exc:
        return _server_problem("bt.receive", exc)
    except _TOOL_ERRORS as exc:
        return CheckResult("bt.receive", Status.FAIL, f"scan mislukt: {exc}")
    return _verdict("bt.receive", found, server_address, "TEST-CLIENT ziet de TEST-SERVER",
                    "TEST-CLIENT ziet de TEST-SERVER niet (ontvanger/antenne defect?)")


def check_transmit(ctx: Context, client_address: str) -> CheckResult:
    """De TEST-CLIENT is zichtbaar; de TEST-SERVER moet hem zien."""
    secs = config.BT_SCAN_SECONDS
    try:
        ctx.client.call("bt_discoverable", enabled=True, _timeout=15)
        try:
            found = ctx.server_ops.bt_scan(secs, client_address)
        finally:
            try:
                ctx.client.call("bt_discoverable", enabled=False, _timeout=15)
            except _TOOL_ERRORS:
                pass
    except OpsError as exc:
        return _server_problem("bt.transmit", exc)
    except _TOOL_ERRORS as exc:
        return CheckResult("bt.transmit", Status.FAIL, f"scan mislukt: {exc}")
    return _verdict("bt.transmit", found, client_address, "TEST-SERVER ziet de TEST-CLIENT",
                    "TEST-SERVER ziet de TEST-CLIENT niet (zender/antenne defect?)")
