"""Wifi van de TEST-CLIENT: de TEST-SERVER speelt accesspoint (2,4 en 5 GHz), de TEST-CLIENT scant en verbindt.

Beheer verloopt over de ethernetkabel, dus de wifi-verbinding mag vrij komen en gaan."""

from __future__ import annotations

import time

from .. import config
from ..agent.client import RpcError
from ..context import Context
from ..models import CheckResult, Status
from ..system.ops import OpsError

_TOOL_ERRORS = (RpcError, OpsError)


def run(ctx: Context) -> list[CheckResult]:
    if ctx.server_ops is None:
        return [CheckResult("wifi", Status.SKIP, "overgeslagen: TEST-SERVER heeft geen systeem-backend")]
    try:
        if not ctx.server_ops.wifi_info()["ifaces"]:
            return [CheckResult("wifi", Status.SKIP, "overgeslagen: de TEST-SERVER heeft geen wifi, dus geen accesspoint")]
        client_info = ctx.client.call("wifi_info")
    except _TOOL_ERRORS as exc:
        return [CheckResult("wifi.radio", Status.FAIL, f"wifi-gegevens niet op te halen: {exc}")]

    radio = check_radio(client_info)
    results = [radio]
    for label, band, channel in config.WIFI_BANDS:
        if radio.status is Status.FAIL:
            results.append(CheckResult(f"wifi.{label}", Status.SKIP, "overgeslagen: geen werkende wifi-radio"))
        else:
            results.append(check_band(ctx, label, band, channel))
    return results


def check_radio(info: dict) -> CheckResult:
    if not info["ifaces"]:
        return CheckResult("wifi.radio", Status.FAIL, "geen wifi-interface op de TEST-CLIENT (defecte chip of firmware)", info)
    blocked = [r for r in info.get("rfkill", []) if r.get("hard_blocked")]
    if blocked:
        return CheckResult("wifi.radio", Status.FAIL, "wifi staat hardwarematig uit (rfkill)", info)
    return CheckResult("wifi.radio", Status.PASS, f"interface {', '.join(info['ifaces'])} aanwezig", info)


def _scan_for_ssid(ctx: Context, freq_check) -> dict | None:
    for attempt in range(config.WIFI_SCAN_TRIES):
        networks = ctx.client.call("wifi_scan", _timeout=60)
        for net in networks:
            if net["ssid"] == config.WIFI_SSID and freq_check(net["freq_mhz"]):
                return net
        if attempt + 1 < config.WIFI_SCAN_TRIES:
            time.sleep(2)
    return None


def check_band(ctx: Context, label: str, band: str, channel: int) -> CheckResult:
    name = f"wifi.{label}"
    is_5g = band == "a"
    details: dict = {"band": band, "channel": channel}
    try:
        try:
            ap = ctx.server_ops.wifi_hotspot_start(config.WIFI_SSID, config.WIFI_PASSWORD, band, channel)
        except OpsError as exc:  # probleem aan de TEST-SERVER, niet aan de TEST-CLIENT
            return CheckResult(name, Status.SKIP, f"hotspot starten op de TEST-SERVER mislukt: {exc}")
        details["hotspot_ip"] = ap["ip"]

        seen = _scan_for_ssid(ctx, lambda f: (f >= 4900) == is_5g)
        if seen is None:
            return CheckResult(name, Status.FAIL, f"TEST-CLIENT ziet het {label}-accesspoint niet (radio/antenne defect?)",
                               details)
        details["scan"] = seen

        connect = ctx.client.call("wifi_connect", ssid=config.WIFI_SSID, password=config.WIFI_PASSWORD, _timeout=60)
        link = ctx.client.call("wifi_link")
        details.update(connect=connect, link=link)
        if not link.get("connected") or not link.get("ip"):
            return CheckResult(name, Status.FAIL, "verbonden zonder IP-adres of verbinding valt weg", details)

        count = config.PING_COUNT
        to_client = ctx.server_ops.ping(link["ip"], count)
        to_ap = ctx.client.call("net_ping", host=ap["ip"], count=count, _timeout=count * 1.3 + 15)
        details.update(ping_server_to_client=to_client, ping_client_to_server=to_ap)
    except _TOOL_ERRORS as exc:
        return CheckResult(name, Status.FAIL, f"test mislukt: {exc}", details)
    finally:
        _cleanup(ctx)

    loss = max(to_client["loss_pct"], to_ap["loss_pct"])
    signal = link.get("signal_dbm")
    summary = (f"verbonden op {link.get('freq_mhz')} MHz, signaal {signal} dBm, "
               f"{link.get('tx_mbit')} Mb/s, verlies {to_client['loss_pct']:.0f}%/{to_ap['loss_pct']:.0f}%")
    if loss > 0:
        return CheckResult(name, Status.FAIL, f"pakketverlies over wifi: {summary}", details)
    if signal is not None and signal < config.WIFI_MIN_SIGNAL_DBM:
        return CheckResult(name, Status.WARN, f"zwak signaal op korte afstand: {summary}", details)
    return CheckResult(name, Status.PASS, summary, details)


def _cleanup(ctx: Context) -> None:
    try:
        ctx.client.call("wifi_forget")
    except _TOOL_ERRORS:
        pass
    try:
        ctx.server_ops.wifi_hotspot_stop()
    except OpsError:
        pass
