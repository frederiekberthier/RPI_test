from __future__ import annotations

import datetime as dt
from collections.abc import Callable

from .checks import bluetooth, gpio, network, power, system, usb, wifi
from .context import Context
from .models import CheckResult, Report, Status

Check = Callable[[Context], list[CheckResult]]

# Volgorde telt: bluetooth deelt een chip met wifi en draait dus erna.
CHECK_GROUPS: dict[str, Check] = {
    "gpio": gpio.run,
    "usb": usb.run,
    "network": network.run,
    "wifi": wifi.run,
    "bluetooth": bluetooth.run,
    "power": power.run,  # laatst: meldt ook onderspanning die tijdens de eerdere tests optrad
}


class Progress:
    """Wordt tijdens een run op de hoogte gehouden (bv. door het scherm). Alles is optioneel."""

    def group_started(self, name: str) -> None: ...

    def result(self, result: CheckResult) -> None: ...

    def should_stop(self) -> bool:
        """True: sla de resterende groepen over (de operator brak af)."""
        return False


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def run_all(ctx: Context, groups: dict[str, Check] | None = None, progress: Progress | None = None) -> Report:
    groups = CHECK_GROUPS if groups is None else groups
    progress = progress or Progress()
    started = _now()
    progress.group_started("connect")
    connect, client_info = system.check_connect(ctx)
    results = [connect]
    progress.result(connect)

    for name, check in groups.items():
        if connect.status is Status.FAIL:
            new = [CheckResult(name, Status.SKIP, "overgeslagen: geen verbinding met de TEST-CLIENT")]
        elif progress.should_stop():
            new = [CheckResult(name, Status.SKIP, "overgeslagen: afgebroken door de operator")]
        else:
            progress.group_started(name)
            try:
                new = check(ctx)
            except Exception as exc:  # een crashende check mag de rest niet blokkeren
                new = [CheckResult(name, Status.FAIL, f"check is gecrasht: {type(exc).__name__}: {exc}")]
        for result in new:
            results.append(result)
            progress.result(result)
    return Report(ctx.server_info, client_info, results, started, _now())
