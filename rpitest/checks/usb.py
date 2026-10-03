"""USB-poorten van de TEST-CLIENT, getest met vier voorbereide sticks in een vaste fixture.

Per slot: stick gevonden, snelheid onderhandeld (USB3 niet teruggevallen naar USB2), data
schrijven en terugleggen zonder fouten, leessnelheid. Daarna het kernellogboek: overstroom,
mislukte enumeratie, USB-resets en -disconnects tijdens de test."""

from __future__ import annotations

from .. import config
from ..agent.client import RpcError
from ..context import Context
from ..models import CheckResult, Status
from ..system.ops import OpsError

_TOOL_ERRORS = (RpcError, OpsError)
FAIL_ALWAYS = {"overcurrent", "enumerate", "xhci"}  # ook als ze al bij het opstarten voorkwamen
FAIL_DURING_TEST = FAIL_ALWAYS | {"disconnect"}


def run(ctx: Context) -> list[CheckResult]:
    slots = ctx.usb_slots or list(config.USB_SLOTS)
    try:
        devices = ctx.client.call("usb_scan", _timeout=30)
        t0 = ctx.client.call("usb_uptime")
    except _TOOL_ERRORS as exc:
        return [CheckResult("usb.scan", Status.FAIL, f"USB-apparaten niet op te halen: {exc}")]

    by_label = {d["fixture_label"]: d for d in devices if d.get("fixture_label")}
    if not by_label:
        others = [d for d in devices if not d.get("is_hub")]
        return [CheckResult(
            "usb.fixture", Status.FAIL,
            "geen enkele teststick gevonden: is de fixture aangesloten en zijn de sticks voorbereid? "
            "(of is de USB-controller van de TEST-CLIENT defect)", {"devices_seen": others})]

    results = [check_slot(ctx, slot, by_label.get(slot["label"])) for slot in slots]
    results.append(check_kernel(ctx, t0))
    return results


def check_slot(ctx: Context, slot: dict, device: dict | None) -> CheckResult:
    name = f"usb.{slot['label']}"
    label = slot.get("name", slot["label"])
    if device is None:
        return CheckResult(name, Status.FAIL,
                           f"{label}: stick niet gevonden (poort defect, slecht contact of stick ontbreekt)")
    details: dict = {"device": device}
    problems: list[str] = []
    warnings: list[str] = []

    speed = device.get("speed_mbit") or 0
    if speed < slot["min_speed_mbit"]:
        problems.append(f"onderhandelt {speed:g} Mb/s i.p.v. minstens {slot['min_speed_mbit']:g} Mb/s "
                        "(contacten of kabel/aansluiting defect)")

    if not device.get("block"):
        problems.append("stick is gevonden maar levert geen opslagapparaat")
    else:
        try:
            storage = ctx.client.call("usb_storage_test", block=device["block"], size_mb=config.USB_TEST_MB,
                                   _timeout=120)
            details["storage"] = storage
            if storage["mismatching_chunks"]:
                problems.append(f"{storage['mismatching_chunks']} van {storage['mb']} blokken komen niet "
                                "overeen na terugleggen (dataverlies)")
            if storage["read_mb_s"] < slot["min_read_mb_s"]:
                warnings.append(f"leessnelheid {storage['read_mb_s']:g} MB/s onder {slot['min_read_mb_s']:g} MB/s")
        except _TOOL_ERRORS as exc:
            problems.append(f"lees/schrijftest mislukt: {exc}")

    prefix = f"{label}: "
    if problems:
        return CheckResult(name, Status.FAIL, prefix + "; ".join(problems + warnings), details)
    storage = details["storage"]
    summary = (f"{prefix}{speed:g} Mb/s, schrijven {storage['write_mb_s']:g} MB/s, "
               f"lezen {storage['read_mb_s']:g} MB/s")
    if warnings:
        return CheckResult(name, Status.WARN, f"{summary}; {'; '.join(warnings)}", details)
    return CheckResult(name, Status.PASS, summary, details)


def check_kernel(ctx: Context, test_start: float) -> CheckResult:
    try:
        events = ctx.client.call("usb_kernel_events", _timeout=30)
    except _TOOL_ERRORS as exc:
        return CheckResult("usb.kernel", Status.WARN, f"kernellogboek niet te lezen: {exc}")
    boot = [e for e in events if e["ts"] < test_start]
    during = [e for e in events if e["ts"] >= test_start]
    failing = [e for e in boot if e["category"] in FAIL_ALWAYS] + \
              [e for e in during if e["category"] in FAIL_DURING_TEST]
    warning = [e for e in during if e["category"] == "reset"]
    details = {"events": events}
    if failing:
        kinds = ", ".join(sorted({e["category"] for e in failing}))
        return CheckResult("usb.kernel", Status.FAIL, f"{len(failing)} USB-fout(en) in het kernellogboek ({kinds}): "
                           f"{failing[0]['text']}", details)
    if warning:
        return CheckResult("usb.kernel", Status.WARN, f"{len(warning)} USB-reset(s) tijdens de test", details)
    return CheckResult("usb.kernel", Status.PASS, "geen USB-fouten in het kernellogboek", details)
