from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config
from . import report as report_mod
from .agent.client import LocalClient, RemoteGpioPort, RpcClient
from .agent.core import Agent
from .context import Context
from .gpio.mock import DUT, TESTER, MockWiring
from .runner import run_all
from .system import mock as sysmock


def _mock_context(faults: list[str]) -> Context:
    wiring = MockWiring()
    sys_faults = []
    for spec in faults:  # bv. stuck_low:D:5  stuck_high:T:9  bridge:D:5:6  open:7  eth_100  no_wifi
        kind, *args = spec.split(":")
        if kind in sysmock.KNOWN_FAULTS:
            sys_faults.append(kind)
        else:
            wiring.add_fault(kind, *args)
    env = sysmock.MockEnv(sys_faults)
    info = {"model": "Raspberry Pi 5 Model B Rev 1.0 (mock)", "ram_mb": 8192, "serial": "MOCK0001"}
    client = LocalClient(Agent(wiring.port(DUT), lambda: info, env.ops(sysmock.DUT)))
    tester_info = {"model": "Raspberry Pi 5 (mock tester)"}
    return Context(wiring.port(TESTER), RemoteGpioPort(client), client, tester_info, env.ops(sysmock.TESTER))


def _real_context(dut_url: str, gpio_chip: str | None):
    # pas hier importeren: vereist gpiod en dus een echte Pi
    from .gpio.real import GpiodPort
    from .system.linux import LinuxOps
    from .sysinfo import pi_info

    port = GpiodPort(gpio_chip)
    client = RpcClient(dut_url)
    return Context(port, RemoteGpioPort(client), client, pi_info(), LinuxOps()), port


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rpitest", description="Test een tweedehands Raspberry Pi")
    parser.add_argument("--mock", action="store_true", help="gesimuleerde testpi + DUT (geen hardware nodig)")
    parser.add_argument("--fault", action="append", default=[], metavar="SPEC",
                        help="fout injecteren in de mock, bv. stuck_low:D:5, bridge:D:5:6, open:7, eth_100, no_wifi, no_bt")
    parser.add_argument("--dut-url", default=f"http://{config.DUT_IP}:{config.AGENT_PORT}",
                        help="adres van de agent op de DUT (echte hardware)")
    parser.add_argument("--gpio-chip", help="pad van de gpiochip van de testpi (standaard: automatisch)")
    parser.add_argument("--out", type=Path, default=Path("reports"), help="map voor de rapporten")
    args = parser.parse_args(argv)

    port = None
    if args.mock:
        ctx = _mock_context(args.fault)
    else:
        try:
            ctx, port = _real_context(args.dut_url, args.gpio_chip)
        except RuntimeError as exc:
            print(f"Fout: {exc}", file=sys.stderr)
            return 2

    try:
        report = run_all(ctx)
    finally:
        if port is not None:
            port.close()
    for r in report.results:
        print(f"[{r.status.value:4}] {r.name}: {r.summary}")
    json_path, html_path = report_mod.save(report, args.out)
    print(f"\nEindoordeel: {report.overall}\nRapport: {html_path}\n         {json_path}")
    return 0 if report.overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
