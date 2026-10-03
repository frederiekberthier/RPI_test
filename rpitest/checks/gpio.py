"""GPIO-checks met twee Pi's die pin-voor-pin met elkaar verbonden zijn.

Aanname: de testpi is zelf in orde (zie de zelftest met een bekend goede DUT). Een fout die
alleen in één richting optreedt, wijst daardoor naar de DUT.
"""

from __future__ import annotations

from collections import defaultdict

from ..context import Context
from ..gpio.ports import EXTERNAL_PULLUP, PINS, Pull, label
from ..models import CheckResult, Status

TESTER_TO_DUT = "tester->dut"
DUT_TO_TESTER = "dut->tester"


def run(ctx: Context) -> list[CheckResult]:
    return [check_pulls(ctx), check_drive(ctx)]


def _summarize(name: str, pins, issues: dict[int, list[str]], extra: str = "") -> CheckResult:
    if not issues:
        return CheckResult(name, Status.PASS, f"alle {len(pins)} pinnen in orde{extra}",
                           {"pins": {p: "OK" for p in pins}})
    bad = ", ".join(label(p) for p in sorted(issues))
    return CheckResult(name, Status.FAIL, f"{len(issues)} van {len(pins)} pinnen met probleem: {bad}",
                       {"pins": {p: issues.get(p, "OK") for p in pins}})


def check_pulls(ctx: Context, pins=PINS) -> CheckResult:
    """Interne pull-up/-down van de DUT. Vindt kortsluiting naar GND/3V3 en defecte pads."""
    ctx.tester_gpio.set_input(pins, Pull.NONE)  # testpi laat de lijnen los
    ctx.dut_gpio.set_input(pins, Pull.UP)
    up = ctx.dut_gpio.read(pins)
    ctx.dut_gpio.set_input(pins, Pull.DOWN)
    down = ctx.dut_gpio.read(pins)
    ctx.dut_gpio.set_input(pins, Pull.NONE)

    issues: dict[int, list[str]] = {}
    for p in pins:
        if up[p] != 1:
            issues.setdefault(p, []).append("pull-up leest 0 (kortsluiting naar GND of defecte pull-up)")
        if p in EXTERNAL_PULLUP:
            continue  # vaste pull-up naar 3V3: pull-down is hier niet te testen
        if down[p] != 0:
            issues.setdefault(p, []).append("pull-down leest 1 (kortsluiting naar 3V3 of defecte pull-down)")
    skipped = sorted(EXTERNAL_PULLUP & set(pins))
    extra = ""
    if skipped:
        extra = f" (pull-down niet testbaar op {', '.join(label(p) for p in skipped)}: vaste pull-up)"
    return _summarize("gpio.pulls", pins, issues, extra)


def _expected(driven: int, level: int, pin: int) -> int:
    """Wat de lezende kant op `pin` moet zien als `driven` op `level` gestuurd wordt.

    level 1: overige pinnen staan op pull-down (0), behalve GPIO2/3 met vaste pull-up.
    level 0: overige pinnen staan op pull-up (1).
    """
    if pin == driven:
        return level
    return 1 if level == 0 or pin in EXTERNAL_PULLUP else 0


def check_drive(ctx: Context, pins=PINS) -> CheckResult:
    """Stuur elke pin hoog en laag vanuit beide kanten; de andere kant leest alle pinnen."""
    # richting -> gelezen pin -> {(gestuurde pin, niveau, gelezen waarde)}
    wrong: dict[str, dict[int, set]] = defaultdict(lambda: defaultdict(set))
    ports = {"tester": ctx.tester_gpio, "dut": ctx.dut_gpio}
    try:
        for direction, (driver, reader) in {
            TESTER_TO_DUT: ("tester", "dut"),
            DUT_TO_TESTER: ("dut", "tester"),
        }.items():
            drv, rd = ports[driver], ports[reader]
            for level in (1, 0):
                pull = Pull.DOWN if level else Pull.UP
                drv.set_input(pins, pull)
                rd.set_input(pins, pull)
                for n in pins:
                    drv.drive(n, level)
                    got = rd.read(pins)
                    drv.set_input([n], pull)  # meteen loslaten: nooit twee uitgangen tegelijk
                    for m in pins:
                        if got[m] != _expected(n, level, m):
                            wrong[direction][m].add((n, level, got[m]))
    finally:
        for port in ports.values():
            port.set_input(pins, Pull.NONE)

    issues, bridges = _diagnose(wrong)
    result = _summarize("gpio.drive", pins, issues)
    result.details["bridges"] = sorted(sorted(b) for b in bridges)
    if bridges:
        pairs = ", ".join(f"{label(a)} - {label(b)}" for a, b in result.details["bridges"])
        result.summary += f"; vermoedelijke kortsluiting tussen pinnen: {pairs}"
    return result


def _diagnose(wrong):
    issues: dict[int, list[str]] = {}
    bridges: set[frozenset[int]] = set()
    stuck_pins: set[int] = set()
    no_follow: dict[int, dict[str, set[int]]] = defaultdict(dict)

    for direction, by_pin in wrong.items():
        for m, entries in by_pin.items():
            others = [e for e in entries if e[0] != m]
            own = {level for n, level, _ in entries if n == m}
            other_pins = {n for n, _, _ in others}
            gots = {g for _, _, g in others}
            if len(other_pins) >= 3 and len(gots) == 1:
                # leest altijd dezelfde verkeerde waarde, wat er ook gestuurd wordt: vastzittende pin
                value = next(iter(gots))
                stuck_pins.add(m)
                msg = f"hangt vast op {'hoog (3V3)' if value else 'laag (GND)'} ({direction})"
                if msg not in issues.setdefault(m, []):
                    issues[m].append(msg)
                continue
            for n in other_pins:
                bridges.add(frozenset({n, m}))
            if own:
                no_follow[m][direction] = own

    for m, per_dir in no_follow.items():
        if m in stuck_pins:
            continue
        if len(per_dir) == 2:
            msg = "geen signaal in beide richtingen (onderbroken verbinding of dode pin)"
        elif TESTER_TO_DUT in per_dir:
            msg = "DUT-pin volgt de testpi niet (defecte ingang/pad of slechte verbinding)"
        else:
            msg = "signaal van DUT-pin komt niet aan (defecte uitgang/pad of slechte verbinding)"
        issues.setdefault(m, []).append(msg)

    for pair in bridges:
        a, b = sorted(pair)
        for p, other in ((a, b), (b, a)):
            issues.setdefault(p, []).append(f"kortsluiting met {label(other)}")
    return issues, bridges
