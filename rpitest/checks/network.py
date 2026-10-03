"""Wired netwerk: linksnelheid, pakketverlies, latentie, doorvoer en ethernetfouten.

De rechtstreekse kabel naar de TEST-SERVER is meteen de testverbinding. Een fout die in beide
richtingen tegelijk optreedt, kan ook aan de kabel of de TEST-SERVER liggen (zie zelftest)."""

from __future__ import annotations

from .. import config
from ..agent.client import RpcError
from ..context import Context
from ..models import CheckResult, Status
from ..system.ops import OpsError

ERROR_FIELDS = ("rx_errors", "tx_errors", "rx_crc_errors")
_TOOL_ERRORS = RpcError  # een fout van de TEST-CLIENT; een OpsError komt van de TEST-SERVER zelf (zie _server_problem)


def _server_problem(name: str, exc: Exception) -> CheckResult:
    return CheckResult(name, Status.SKIP, f"overgeslagen: probleem aan de TEST-SERVER, niet aan de TEST-CLIENT: {exc}")


def run(ctx: Context) -> list[CheckResult]:
    if ctx.server_ops is None:
        return [CheckResult("network", Status.SKIP, "overgeslagen: TEST-SERVER heeft geen systeem-backend")]
    try:
        client_if = ctx.client.call("net_iface_info")
        server_if = ctx.server_ops.net_iface_info()
    except OpsError as exc:
        return [_server_problem("net.link", exc)]
    except _TOOL_ERRORS as exc:
        return [CheckResult("net.link", Status.FAIL, f"ethernetgegevens niet op te halen: {exc}")]
    return [
        check_link(client_if, server_if),
        check_latency(ctx),
        *check_throughput(ctx, client_if, server_if),
    ]


def check_link(client_if: dict, server_if: dict) -> CheckResult:
    details = {"client": client_if, "server": server_if}
    d, t = client_if.get("speed_mbit"), server_if.get("speed_mbit")
    if client_if.get("carrier") != 1 or d is None:
        return CheckResult("net.link", Status.FAIL, "TEST-CLIENT meldt geen link", details)
    # beide kanten van de kabel onderhandelen dezelfde snelheid: de laagste telt, en poort en kabel zijn niet te scheiden
    speed = min(d, t) if t else d
    if speed >= 1000:
        return CheckResult("net.link", Status.PASS, f"link 1000 Mb/s {client_if.get('duplex')}, MAC {client_if.get('mac')}",
                           details)
    return CheckResult("net.link", Status.FAIL,
                       f"link op {speed} Mb/s in plaats van 1000: defecte ethernetpoort of kabel (defect aderpaar)", details)


def check_latency(ctx: Context) -> CheckResult:
    count = config.PING_COUNT
    try:
        to_client = ctx.server_ops.ping(config.CLIENT_IP, count)
        to_server = ctx.client.call("net_ping", host=config.SERVER_IP, count=count, _timeout=count * 1.3 + 15)
    except OpsError as exc:
        return _server_problem("net.latency", exc)
    except _TOOL_ERRORS as exc:
        return CheckResult("net.latency", Status.FAIL, f"ping mislukt: {exc}")
    details = {"server->client": to_client, "client->server": to_server}
    lost = max(to_client["loss_pct"], to_server["loss_pct"])
    rtts = [r["rtt_avg_ms"] for r in (to_client, to_server) if r["rtt_avg_ms"] is not None]
    summary = f"verlies {to_client['loss_pct']:.0f}%/{to_server['loss_pct']:.0f}%, gem. RTT " + (
        "/".join(f"{r:.2f}" for r in rtts) + " ms" if rtts else "n.v.t.")
    if lost > 0:
        return CheckResult("net.latency", Status.FAIL, f"pakketverlies: {summary}", details)
    if rtts and max(rtts) > config.PING_MAX_RTT_MS:
        return CheckResult("net.latency", Status.WARN, f"hoge latentie: {summary}", details)
    return CheckResult("net.latency", Status.PASS, summary, details)


def _classify(mbit: float) -> Status:
    if mbit >= config.NET_MIN_MBIT_PASS:
        return Status.PASS
    return Status.WARN if mbit >= config.NET_MIN_MBIT_WARN else Status.FAIL


def _error_total(before: dict, after: dict) -> int:
    return sum(max(0, (after["stats"].get(f) or 0) - (before["stats"].get(f) or 0)) for f in ERROR_FIELDS)


def check_throughput(ctx: Context, client_before: dict, server_before: dict) -> list[CheckResult]:
    secs = config.IPERF_SECONDS
    try:
        ctx.client.call("iperf3_server_start")
        try:
            forward = ctx.server_ops.iperf3_client(config.CLIENT_IP, secs, reverse=False)
            reverse = ctx.server_ops.iperf3_client(config.CLIENT_IP, secs, reverse=True)
        finally:
            try:
                ctx.client.call("iperf3_server_stop")
            except _TOOL_ERRORS:
                pass
        client_after = ctx.client.call("net_iface_info")
        server_after = ctx.server_ops.net_iface_info()
    except OpsError as exc:
        return [_server_problem("net.throughput", exc), _server_problem("net.errors", exc)]
    except _TOOL_ERRORS as exc:
        return [CheckResult("net.throughput", Status.FAIL, f"doorvoertest mislukt: {exc}"),
                CheckResult("net.errors", Status.SKIP, "overgeslagen: doorvoertest mislukt")]

    details = {"server->client": forward, "client->server": reverse}
    statuses = [_classify(forward["mbit_per_s"]), _classify(reverse["mbit_per_s"])]
    worst = Status.FAIL if Status.FAIL in statuses else Status.WARN if Status.WARN in statuses else Status.PASS
    throughput = CheckResult(
        "net.throughput", worst,
        f"server->client {forward['mbit_per_s']:.0f} Mb/s, client->server {reverse['mbit_per_s']:.0f} Mb/s", details)

    client_errors, server_errors = _error_total(client_before, client_after), _error_total(server_before, server_after)
    total = client_errors + server_errors
    status = (Status.FAIL if total >= config.NET_ERRORS_FAIL
              else Status.WARN if total >= config.NET_ERRORS_WARN else Status.PASS)
    errors = CheckResult("net.errors", status, f"{client_errors} fouten op TEST-CLIENT, {server_errors} op TEST-SERVER tijdens de test",
                         {"client": client_errors, "server": server_errors})
    return [throughput, errors]
