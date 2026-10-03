"""Wired netwerk: linksnelheid, pakketverlies, latentie, doorvoer en ethernetfouten.

De rechtstreekse kabel naar de testpi is meteen de testverbinding. Een fout die in beide
richtingen tegelijk optreedt, kan ook aan de kabel of de testpi liggen (zie zelftest)."""

from __future__ import annotations

from .. import config
from ..agent.client import RpcError
from ..context import Context
from ..models import CheckResult, Status
from ..system.ops import OpsError

ERROR_FIELDS = ("rx_errors", "tx_errors", "rx_crc_errors")
_TOOL_ERRORS = (RpcError, OpsError)


def run(ctx: Context) -> list[CheckResult]:
    if ctx.tester_ops is None:
        return [CheckResult("network", Status.SKIP, "overgeslagen: testpi heeft geen systeem-backend")]
    try:
        dut_if = ctx.dut.call("net_iface_info")
        tester_if = ctx.tester_ops.net_iface_info()
    except _TOOL_ERRORS as exc:
        return [CheckResult("net.link", Status.FAIL, f"ethernetgegevens niet op te halen: {exc}")]
    return [
        check_link(dut_if, tester_if),
        check_latency(ctx),
        *check_throughput(ctx, dut_if, tester_if),
    ]


def check_link(dut_if: dict, tester_if: dict) -> CheckResult:
    details = {"dut": dut_if, "tester": tester_if}
    d, t = dut_if.get("speed_mbit"), tester_if.get("speed_mbit")
    if dut_if.get("carrier") != 1 or d is None:
        return CheckResult("net.link", Status.FAIL, "DUT meldt geen link", details)
    if d >= 1000 and (t or 0) >= 1000:
        return CheckResult("net.link", Status.PASS, f"link 1000 Mb/s {dut_if.get('duplex')}, MAC {dut_if.get('mac')}",
                           details)
    if (t or 0) < 1000:
        return CheckResult("net.link", Status.WARN,
                           f"testpi meldt {t} Mb/s: controleer testkabel/testpi (DUT: {d} Mb/s)", details)
    return CheckResult("net.link", Status.FAIL,
                       f"DUT onderhandelt slechts {d} Mb/s (defect aderpaar of ethernetaansluiting)", details)


def check_latency(ctx: Context) -> CheckResult:
    count = config.PING_COUNT
    try:
        to_dut = ctx.tester_ops.ping(config.DUT_IP, count)
        to_tester = ctx.dut.call("net_ping", host=config.TESTER_IP, count=count, _timeout=count * 1.3 + 15)
    except _TOOL_ERRORS as exc:
        return CheckResult("net.latency", Status.FAIL, f"ping mislukt: {exc}")
    details = {"tester->dut": to_dut, "dut->tester": to_tester}
    lost = max(to_dut["loss_pct"], to_tester["loss_pct"])
    rtts = [r["rtt_avg_ms"] for r in (to_dut, to_tester) if r["rtt_avg_ms"] is not None]
    summary = f"verlies {to_dut['loss_pct']:.0f}%/{to_tester['loss_pct']:.0f}%, gem. RTT " + (
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


def check_throughput(ctx: Context, dut_before: dict, tester_before: dict) -> list[CheckResult]:
    secs = config.IPERF_SECONDS
    try:
        ctx.dut.call("iperf3_server_start")
        try:
            forward = ctx.tester_ops.iperf3_client(config.DUT_IP, secs, reverse=False)
            reverse = ctx.tester_ops.iperf3_client(config.DUT_IP, secs, reverse=True)
        finally:
            try:
                ctx.dut.call("iperf3_server_stop")
            except _TOOL_ERRORS:
                pass
        dut_after = ctx.dut.call("net_iface_info")
        tester_after = ctx.tester_ops.net_iface_info()
    except _TOOL_ERRORS as exc:
        return [CheckResult("net.throughput", Status.FAIL, f"doorvoertest mislukt: {exc}"),
                CheckResult("net.errors", Status.SKIP, "overgeslagen: doorvoertest mislukt")]

    details = {"tester->dut": forward, "dut->tester": reverse}
    statuses = [_classify(forward["mbit_per_s"]), _classify(reverse["mbit_per_s"])]
    worst = Status.FAIL if Status.FAIL in statuses else Status.WARN if Status.WARN in statuses else Status.PASS
    throughput = CheckResult(
        "net.throughput", worst,
        f"tester->dut {forward['mbit_per_s']:.0f} Mb/s, dut->tester {reverse['mbit_per_s']:.0f} Mb/s", details)

    dut_errors, tester_errors = _error_total(dut_before, dut_after), _error_total(tester_before, tester_after)
    total = dut_errors + tester_errors
    status = (Status.FAIL if total >= config.NET_ERRORS_FAIL
              else Status.WARN if total >= config.NET_ERRORS_WARN else Status.PASS)
    errors = CheckResult("net.errors", status, f"{dut_errors} fouten op DUT, {tester_errors} op testpi tijdens de test",
                         {"dut": dut_errors, "tester": tester_errors})
    return [throughput, errors]
