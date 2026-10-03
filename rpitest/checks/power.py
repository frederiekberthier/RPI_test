"""Voeding, temperatuur en rekenstabiliteit van de TEST-CLIENT onder belasting.

De TEST-CLIENT draait ca. een minuut op alle kernen met een deterministische rekentaak en een
geheugentest, terwijl de TEST-SERVER elke paar seconden temperatuur, klokfrequentie en de
throttled-vlaggen van de firmware uitleest.

Onderspanning kan ook aan de testvoeding liggen. Gebruik een goede voeding en maak de zelftest
met een bekend goede Pi; een TEST-CLIENT met een slechte stroomvoorziening valt daar dan door af."""

from __future__ import annotations

import statistics
import time

from .. import config
from ..agent.client import RpcError
from ..context import Context
from ..models import CheckResult, Status
from ..system.ops import OpsError
from ..system.parsers import decode_throttled

_TOOL_ERRORS = (RpcError, OpsError)
SUPPLY_KEY = "EXT5V_V"  # ingangsspanning op de Pi 5 (vcgencmd pmic_read_adc)


def run(ctx: Context) -> list[CheckResult]:
    seconds = config.STRESS_SECONDS
    try:
        samples = [ctx.client.call("power_sample")]
        ctx.client.call("stress_start", seconds=seconds, ram_mb=config.STRESS_RAM_MB)
    except _TOOL_ERRORS as exc:
        return [CheckResult("power.sensors", Status.FAIL, f"metingen of belasting starten mislukt: {exc}")]

    try:
        deadline = time.monotonic() + seconds + 60
        while True:
            time.sleep(config.STRESS_POLL_S)
            samples.append(ctx.client.call("power_sample"))
            if not ctx.client.call("stress_poll")["running"]:
                break
            if time.monotonic() > deadline:
                raise OpsError("belastingstest eindigde niet op tijd")
        result = ctx.client.call("stress_result", _timeout=30)
        samples.append(ctx.client.call("power_sample"))
    except _TOOL_ERRORS as exc:
        _stop(ctx)
        return [CheckResult("power.sensors", Status.FAIL, f"belastingstest mislukt: {exc}")]
    return evaluate(samples, result)


def _stop(ctx: Context) -> None:
    try:
        ctx.client.call("stress_stop")
    except _TOOL_ERRORS:
        pass


def evaluate(samples: list[dict], result: dict) -> list[CheckResult]:
    """Pure beoordeling van de metingen; samples[0] is de meting in rust, de rest onder belasting."""
    return [
        check_sensors(samples),
        check_supply(samples),
        check_thermal(samples),
        check_cpu(samples, result),
        check_memory(result),
    ]


def check_sensors(samples: list[dict]) -> CheckResult:
    missing = [name for name in ("temp_c", "freq_mhz") if all(s.get(name) is None for s in samples)]
    details = {"first": samples[0], "last": samples[-1], "samples": len(samples)}
    if missing:
        return CheckResult("power.sensors", Status.FAIL, f"niet leesbaar: {', '.join(missing)}", details)
    if all(s.get("throttled") is None for s in samples):
        return CheckResult("power.sensors", Status.WARN,
                           "temperatuur en frequentie leesbaar, maar vcgencmd get_throttled ontbreekt "
                           "(onderspanning niet te beoordelen)", details)
    return CheckResult("power.sensors", Status.PASS, f"{len(samples)} metingen", details)


def _flag(samples: list[dict], name: str) -> bool:
    return any(decode_throttled(s.get("throttled")).get(name) for s in samples)


def check_supply(samples: list[dict]) -> CheckResult:
    volts = [s["volts"][SUPPLY_KEY] for s in samples if SUPPLY_KEY in (s.get("volts") or {})]
    details = {"min_input_volt": min(volts) if volts else None}
    if _flag(samples[1:], "undervoltage_now"):
        return CheckResult("power.supply", Status.FAIL,
                           "onderspanning tijdens de belasting (defecte voedingsingang, of een te zwakke "
                           "testvoeding: controleer met een bekend goede Pi)", details)
    if volts and min(volts) < config.MIN_5V_VOLT:
        return CheckResult("power.supply", Status.WARN,
                           f"ingangsspanning zakte tot {min(volts):.2f} V (minimum {config.MIN_5V_VOLT} V)", details)
    if _flag(samples[:1], "undervoltage_occurred"):
        return CheckResult("power.supply", Status.WARN,
                           "onderspanning sinds het opstarten (voor de belastingstest)", details)
    note = f", minimale ingangsspanning {min(volts):.2f} V" if volts else ""
    return CheckResult("power.supply", Status.PASS, f"geen onderspanning{note}", details)


def check_thermal(samples: list[dict]) -> CheckResult:
    temps = [s["temp_c"] for s in samples if s.get("temp_c") is not None]
    if not temps:
        return CheckResult("power.thermal", Status.SKIP, "geen temperatuur gemeten")
    idle, peak = temps[0], max(temps)
    loaded = samples[1:]
    ratios = [s["freq_mhz"] / s["freq_max_mhz"] for s in loaded if s.get("freq_mhz") and s.get("freq_max_mhz")]
    lowest = min(ratios) if ratios else None
    details = {"idle_c": idle, "peak_c": peak, "lowest_freq_ratio": lowest}
    summary = f"rust {idle:.0f} graden, piek {peak:.0f} graden"
    if lowest is not None:
        summary += f", laagste klokfrequentie {lowest * 100:.0f}% van het maximum"

    if peak >= config.TEMP_FAIL_C:
        return CheckResult("power.thermal", Status.FAIL, f"te heet: {summary}", details)
    throttled = _flag(loaded, "soft_temp_limit_now") or (
        lowest is not None and lowest < config.THROTTLE_FREQ_RATIO and not _flag(loaded, "undervoltage_now"))
    if throttled or peak >= config.TEMP_WARN_C:
        return CheckResult("power.thermal", Status.WARN,
                           f"throttling of zeer warm (koeling ontbreekt of werkt slecht?): {summary}", details)
    if idle >= config.TEMP_IDLE_WARN_C:
        return CheckResult("power.thermal", Status.WARN, f"al warm in rust: {summary}", details)
    return CheckResult("power.thermal", Status.PASS, summary, details)


def check_cpu(samples: list[dict], result: dict) -> CheckResult:
    cpu = result.get("cpu", [])
    online, present = samples[-1].get("cores_online"), samples[-1].get("cores_present")
    details = {"workers": cpu, "cores_online": online, "cores_present": present, "errors": result.get("errors", [])}
    problems = []
    if online is not None and online < config.EXPECTED_CORES:
        problems.append(f"slechts {online} van {config.EXPECTED_CORES} kernen actief")
    bad = sum(w["bad"] for w in cpu)
    if bad:
        problems.append(f"{bad} verkeerde rekenresultaten")
    if result.get("errors"):
        problems.append("; ".join(result["errors"]))
    if not cpu:
        problems.append("geen rekenresultaten")
    if problems:
        return CheckResult("power.cpu", Status.FAIL, "; ".join(problems), details)

    rounds = [w["rounds"] for w in cpu]
    median = statistics.median(rounds)
    if min(rounds) < config.SLOW_CORE_RATIO * median:
        return CheckResult("power.cpu", Status.WARN,
                           f"een kern is veel trager ({min(rounds)} tegen mediaan {median:g} rondes)", details)
    return CheckResult("power.cpu", Status.PASS, f"{len(cpu)} kernen, {sum(rounds)} rondes zonder fouten", details)


def check_memory(result: dict) -> CheckResult:
    ram = result.get("ram")
    if ram is None:
        return CheckResult("power.memory", Status.WARN, "geheugentest is niet uitgevoerd (te weinig vrij geheugen?)")
    if ram["bad"]:
        return CheckResult("power.memory", Status.FAIL,
                           f"{ram['bad']} foute blokken in {ram['mb']} MB na {ram['passes']} rondes", ram)
    return CheckResult("power.memory", Status.PASS, f"{ram['mb']} MB, {ram['passes']} rondes zonder fouten", ram)
