"""Bluetooth van de DUT: ontvangen (DUT ziet de testpi) en zenden (testpi ziet de DUT).

Bluetooth en wifi delen op de Pi dezelfde chip; deze check draait daarom na de wifi-check."""

from __future__ import annotations

from .. import config
from ..agent.client import RpcError
from ..context import Context
from ..models import CheckResult, Status
from ..system.ops import OpsError

_TOOL_ERRORS = (RpcError, OpsError)


def run(ctx: Context) -> list[CheckResult]:
    if ctx.tester_ops is None:
        return [CheckResult("bluetooth", Status.SKIP, "overgeslagen: testpi heeft geen systeem-backend")]
    try:
        tester = ctx.tester_ops.bt_info()
        if not tester["present"]:
            return [CheckResult("bluetooth", Status.SKIP, "overgeslagen: de testpi heeft geen bluetooth-controller")]
        dut = ctx.dut.call("bt_info")
    except _TOOL_ERRORS as exc:
        return [CheckResult("bt.controller", Status.FAIL, f"bluetooth-gegevens niet op te halen: {exc}")]

    controller = check_controller(dut)
    if controller.status is Status.FAIL:
        return [controller,
                CheckResult("bt.receive", Status.SKIP, "overgeslagen: geen werkende controller"),
                CheckResult("bt.transmit", Status.SKIP, "overgeslagen: geen werkende controller")]
    return [controller, check_receive(ctx, tester["address"]), check_transmit(ctx, dut["address"])]


def check_controller(info: dict) -> CheckResult:
    if not info["present"]:
        return CheckResult("bt.controller", Status.FAIL, "geen bluetooth-controller op de DUT", info)
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


def check_receive(ctx: Context, tester_address: str) -> CheckResult:
    """De testpi is zichtbaar; de DUT moet hem zien."""
    secs = config.BT_SCAN_SECONDS
    try:
        ctx.tester_ops.bt_discoverable(True)
        try:
            found = ctx.dut.call("bt_scan", seconds=secs, forget_mac=tester_address, _timeout=secs + 25)
        finally:
            ctx.tester_ops.bt_discoverable(False)
    except _TOOL_ERRORS as exc:
        return CheckResult("bt.receive", Status.FAIL, f"scan mislukt: {exc}")
    return _verdict("bt.receive", found, tester_address, "DUT ziet de testpi",
                    "DUT ziet de testpi niet (ontvanger/antenne defect?)")


def check_transmit(ctx: Context, dut_address: str) -> CheckResult:
    """De DUT is zichtbaar; de testpi moet hem zien."""
    secs = config.BT_SCAN_SECONDS
    try:
        ctx.dut.call("bt_discoverable", enabled=True, _timeout=15)
        try:
            found = ctx.tester_ops.bt_scan(secs, dut_address)
        finally:
            try:
                ctx.dut.call("bt_discoverable", enabled=False, _timeout=15)
            except _TOOL_ERRORS:
                pass
    except _TOOL_ERRORS as exc:
        return CheckResult("bt.transmit", Status.FAIL, f"scan mislukt: {exc}")
    return _verdict("bt.transmit", found, dut_address, "testpi ziet de DUT",
                    "testpi ziet de DUT niet (zender/antenne defect?)")
