from __future__ import annotations

import datetime as dt
from collections.abc import Callable

from .checks import bluetooth, gpio, network, system, wifi
from .context import Context
from .models import CheckResult, Report, Status

Check = Callable[[Context], list[CheckResult]]

# Volgorde telt: bluetooth deelt een chip met wifi en draait dus erna.
CHECK_GROUPS: dict[str, Check] = {
    "gpio": gpio.run,
    "network": network.run,
    "wifi": wifi.run,
    "bluetooth": bluetooth.run,
}


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def run_all(ctx: Context, groups: dict[str, Check] | None = None) -> Report:
    groups = CHECK_GROUPS if groups is None else groups
    started = _now()
    connect, dut_info = system.check_connect(ctx)
    results = [connect]
    for name, check in groups.items():
        if connect.status is Status.FAIL:
            results.append(CheckResult(name, Status.SKIP, "overgeslagen: geen verbinding met de DUT"))
            continue
        try:
            results.extend(check(ctx))
        except Exception as exc:  # een crashende check mag de rest niet blokkeren
            results.append(CheckResult(name, Status.FAIL, f"check is gecrasht: {type(exc).__name__}: {exc}"))
    return Report(ctx.tester_info, dut_info, results, started, _now())
